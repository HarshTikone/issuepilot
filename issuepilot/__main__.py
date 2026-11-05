import argparse
import json
import logging
import os
import shutil
import signal
import subprocess
import threading
import time
from collections import Counter
from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path
from urllib.request import Request, urlopen

from .agent import HermesDocker
from .config import Config
from .demo import ISSUE, run_demo
from .github import AppAuth, GitHub, rs256_signer
from .health import start_health
from .providers import ProviderRouter
from .store import ProcessLock, Store, restore
from .worker import Worker


def github_for(cfg):
    if cfg.auth == "app":
        auth = AppAuth(cfg.app_id, cfg.installation_id, cfg.repo, rs256_signer(cfg.app_key_file))
        return GitHub(cfg.repo, auth)
    return GitHub(cfg.repo, os.environ["GITHUB_TOKEN"])


def ping(url, ok):
    """Push heartbeat for a monitor such as Healthchecks.io; failures here never stop the worker."""
    if not url:
        return
    try:
        with urlopen(Request(url if ok else url.rstrip("/") + "/fail", headers={"User-Agent": "IssuePilot/0.2"}),
                     timeout=10):
            pass
    except OSError as exc:
        logging.warning("heartbeat_failed error_type=%s", type(exc).__name__)


def main():
    parser = argparse.ArgumentParser(prog="issuepilot", description="IssuePilot: autonomous GitHub issue investigation")
    parser.add_argument("--config", default="config.json")
    sub = parser.add_subparsers(dest="command", required=True)
    demo = sub.add_parser("demo", help="Offline simulation; does not use Hermes or GitHub")
    demo.add_argument("--output", default="demo-output")
    sub.add_parser("check", help="Check configuration, GitHub access and the pinned local image; no model call")
    run = sub.add_parser("run", help="Poll GitHub and automatically publish reports")
    run.add_argument("--once", action="store_true", help="Discover issues and process one due job, then exit")
    sub.add_parser("status", help="Show durable job states")
    sub.add_parser("usage", help="Show model budget reserved in the last 24 hours, per provider")
    retry = sub.add_parser("retry", help="Requeue a failed or cancelled job")
    retry.add_argument("number", type=int)
    export = sub.add_parser("export", help="Export operational evidence; inspect and redact before sharing")
    export.add_argument("--output", default="evidence.json")
    backup = sub.add_parser("backup", help="Write a consistent, integrity-checked copy of the job database")
    backup.add_argument("--output", required=True)
    rest = sub.add_parser("restore", help="Restore a backup into an empty data directory; stop the service first")
    rest.add_argument("backup")
    smoke = sub.add_parser("smoke-agent", help="Run one real Hermes investigation; consumes model quota, posts nothing")
    smoke.add_argument("--provider", help="Provider name from config; default is the first one")
    sub.add_parser("cleanup", help="Remove orphaned IssuePilot task containers on this dedicated host")
    evaluate = sub.add_parser("eval", help="Run the pilot benchmark; see eval/README.md")
    evaluate.add_argument("--cases", default="eval/cases")
    evaluate.add_argument("--mode", choices=("oracle", "retrieval", "all-files"), required=True)
    evaluate.add_argument("--output", default="eval/results")
    evaluate.add_argument("--limit", type=int, default=0, help="Stop after this many new runs (pacing)")
    evaluate.add_argument("--provider", default="", help="Provider name from config; default is the first one")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = Config.load(args.config)
    root = Path(__file__).resolve().parent.parent
    if args.command == "demo":
        print(json.dumps(run_demo(root, args.output, cfg), indent=2))
        return
    if args.command == "check":
        cfg.validate_live()
        github = github_for(cfg)
        if not shutil.which("docker"):
            raise ValueError("Docker is missing")
        subprocess.run(["docker", "image", "inspect", cfg.hermes_image], capture_output=True, timeout=15, check=True)
        github.request(f"/repos/{cfg.repo}")
        github.actor_id = github.auth.actor_id(github)
        if not cfg.retrieval:
            github.context(cfg.branch, cfg.context_paths)
        print("Configuration, provider keys, GitHub identity and read access, and the local image checked.")
        print("Model execution and GitHub comment write access still need the live acceptance test.")
        return
    if args.command == "restore":
        restore(args.backup, cfg.data_dir / "jobs.sqlite3")
        print("Restored. Start the service and check `status`.")
        return
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    read_only = ("status", "export", "usage", "backup", "eval")
    guard = nullcontext() if args.command in read_only else ProcessLock(cfg.data_dir / "worker.lock")
    with guard:
        if args.command == "cleanup":
            HermesDocker.cleanup_orphans()
            return
        store = Store(cfg.data_dir / "jobs.sqlite3")
        try:
            if args.command == "smoke-agent":
                cfg.validate_live()
                specs = [s for s in cfg.routes if s.name == (args.provider or cfg.routes[0].name)]
                if not specs:
                    raise ValueError("Unknown provider name")
                files = {"demo_app/discounts.py": (root / "demo_app/discounts.py").read_text(encoding="utf-8")}
                router = ProviderRouter(replace(cfg, providers=tuple(specs)), store, HermesDocker(cfg), "smoke")
                result = router.investigate(ISSUE, "0" * 40, files)
                path = cfg.data_dir / f"hermes-smoke-{result.provider}.json"
                path.write_text(json.dumps({"mode": "real-hermes-smoke", "image": cfg.hermes_image,
                                            "provider": result.provider, "model": result.model,
                                            "seconds": result.seconds, "finished_at": time.time(),
                                            "report": result.report}, indent=2), encoding="utf-8")
                print("Real Hermes returned a valid investigation. Report saved to " + str(path))
                return
            if args.command == "eval":
                from .evaluation import run_benchmark
                summary = run_benchmark(cfg, store, Path(args.cases), args.mode, Path(args.output), args.limit,
                                        provider=args.provider)
                print(json.dumps(summary, indent=2))
                return
            if args.command == "status":
                for job in store.jobs():
                    print(json.dumps({key: job[key] for key in ("repo", "number", "state", "attempts", "error",
                                                                 "provider", "comment_url")}))
                print(json.dumps(store.health()))
                return
            if args.command == "usage":
                for row in store.usage_summary():
                    print(json.dumps(row))
                return
            if args.command == "backup":
                print(json.dumps(store.backup(args.output)))
                return
            if args.command == "retry":
                store.retry(cfg.repo, args.number)
                print("Job requeued. The service will pick it up on its next cycle.")
                return
            if args.command == "export":
                jobs = [{key: j[key] for key in ("repo", "number", "state", "attempts", "comment_url", "updated_at",
                                                 "provider", "model")} for j in store.jobs()]
                note = "Local records alone do not prove external completion; verify comment URLs and SSH evidence."
                evidence = {"kind": "operational-records", "note": note,
                            "exported_at": time.time(), "hermes_image": cfg.hermes_image, "jobs": jobs,
                            "usage_24h": store.usage_summary()}
                Path(args.output).write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
                print("Exported " + args.output)
                return
            cfg.validate_live()
            github = github_for(cfg)
            runner = HermesDocker(cfg)
            runner.cleanup_orphans()
            store.recover()
            status = {"last_poll_ok": False, "last_cycle": 0, "current_issue": None, "jobs": {}}
            server = start_health(cfg.health_port, status, cfg.poll_seconds * 3 + cfg.timeout_seconds + 60)
            stop = threading.Event()
            for signum in (signal.SIGINT, signal.SIGTERM):
                signal.signal(signum, lambda *_: stop.set())
            worker = Worker(cfg, store, github, ProviderRouter(cfg, store, runner), status)
            try:
                while not stop.is_set():
                    delay = cfg.poll_seconds
                    failed_before = store.health()["failed_jobs"]
                    try:
                        worker.discover()
                        status["last_poll_ok"] = True
                        status.pop("poll_error", None)
                    except Exception as exc:
                        status["last_poll_ok"] = False
                        status["poll_error"] = type(exc).__name__
                        delay = max(delay, getattr(exc, "retry_after", 60))
                        logging.warning("discovery_failed error_type=%s", type(exc).__name__)
                    # Process the durable queue even if discovering new issues failed.
                    if not stop.is_set():
                        worker.process_one()
                    health = store.health()
                    status.update(health, last_cycle=time.time(),
                                  jobs=dict(Counter(j["state"] for j in store.jobs())))
                    ping(cfg.heartbeat_url, status["last_poll_ok"] and health["failed_jobs"] == failed_before)
                    if args.once:
                        break
                    stop.wait(delay)
            finally:
                server.shutdown()
                server.server_close()
        finally:
            store.close()


def cli():
    try:
        main()
    except (ValueError, RuntimeError) as exc:
        # Only these application-generated messages are safe to show. Model and HTTP
        # exceptions inside the worker are reduced to types before reaching logs.
        raise SystemExit(str(exc)) from None


if __name__ == "__main__":
    cli()
