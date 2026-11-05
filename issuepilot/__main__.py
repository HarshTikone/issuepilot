import argparse
import json
import logging
import os
import shutil
import signal
import subprocess
import threading
import time
from contextlib import nullcontext
from collections import Counter
from pathlib import Path

from .agent import HermesDocker
from .config import Config
from .demo import ISSUE, run_demo
from .github import GitHub
from .health import start_health
from .store import ProcessLock, Store
from .worker import Worker


def connections(cfg):
    cfg.validate_live()
    return GitHub(cfg.repo, os.environ["GITHUB_TOKEN"]), HermesDocker(cfg)


def main():
    parser = argparse.ArgumentParser(description="IssuePilot: autonomous GitHub issue investigation")
    parser.add_argument("--config", default="config.json")
    sub = parser.add_subparsers(dest="command", required=True)
    demo = sub.add_parser("demo", help="Offline simulation; does not use Hermes or GitHub")
    demo.add_argument("--output", default="demo-output")
    sub.add_parser("check", help="Check configuration, GitHub access and the pinned local image; no model call")
    run = sub.add_parser("run", help="Poll GitHub and automatically publish reports")
    run.add_argument("--once", action="store_true", help="Discover issues and process one due job, then exit")
    sub.add_parser("status", help="Show durable job states")
    retry = sub.add_parser("retry", help="Requeue a failed or cancelled job")
    retry.add_argument("number", type=int)
    export = sub.add_parser("export", help="Export operational evidence; inspect and redact before sharing")
    export.add_argument("--output", default="evidence.json")
    sub.add_parser("smoke-agent", help="Run one real Hermes investigation; consumes model credit, posts nothing")
    sub.add_parser("cleanup", help="Remove orphaned IssuePilot task containers on this dedicated host")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = Config.load(args.config)
    root = Path(__file__).resolve().parent.parent
    if args.command == "demo":
        print(json.dumps(run_demo(root, args.output, cfg), indent=2))
        return
    if args.command == "check":
        github, agent = connections(cfg)
        if not shutil.which("docker"):
            raise ValueError("Docker is missing")
        subprocess.run(["docker", "image", "inspect", cfg.hermes_image], capture_output=True, timeout=15, check=True)
        github.request("/user")
        github.request(f"/repos/{cfg.repo}")
        github.context(cfg.branch, cfg.context_paths)
        print("Configuration, provider key format, GitHub read access, source paths and local image checked.")
        print("Model execution and GitHub comment write access still need the live acceptance test.")
        return
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    guard = nullcontext() if args.command in ("status", "export") else ProcessLock(cfg.data_dir / "worker.lock")
    with guard:
        if args.command == "cleanup":
            HermesDocker.cleanup_orphans()
            return
        if args.command == "smoke-agent":
            cfg.validate_live()
            agent = HermesDocker(cfg)
            files = {"demo_app/discounts.py": (root / "demo_app/discounts.py").read_text(encoding="utf-8")}
            report = agent.investigate(ISSUE, "0" * 40, files)
            path = cfg.data_dir / "hermes-smoke-report.json"
            path.write_text(json.dumps({"mode": "real-hermes-smoke", "image": cfg.hermes_image,
                                        "model": cfg.model, "provider": cfg.provider,
                                        "finished_at": time.time(), "report": report}, indent=2), encoding="utf-8")
            print("Real Hermes returned a valid investigation. Report saved to " + str(path))
            return
        store = Store(cfg.data_dir / "jobs.sqlite3")
        try:
            if args.command == "status":
                for job in store.jobs():
                    print(json.dumps({key: job[key] for key in ("repo", "number", "state", "attempts", "error", "comment_url")}))
                return
            if args.command == "retry":
                store.retry(cfg.repo, args.number)
                print("Job requeued. The service will pick it up on its next cycle.")
                return
            if args.command == "export":
                jobs = [{key: j[key] for key in ("repo", "number", "state", "attempts", "comment_url", "updated_at")}
                        for j in store.jobs()]
                evidence = {"kind": "operational-records", "note": "Local records alone do not prove external completion; verify comment URLs and SSH evidence.",
                            "exported_at": time.time(), "hermes_image": cfg.hermes_image, "jobs": jobs}
                Path(args.output).write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
                print("Exported " + args.output)
                return
            github, agent = connections(cfg)
            agent.cleanup_orphans()
            store.recover()
            status = {"last_poll_ok": False, "last_cycle": 0, "current_issue": None, "jobs": {}}
            server = start_health(cfg.health_port, status, cfg.poll_seconds * 3 + cfg.timeout_seconds + 60)
            stop = threading.Event()
            for signum in (signal.SIGINT, signal.SIGTERM):
                signal.signal(signum, lambda *_: stop.set())
            worker = Worker(cfg, store, github, agent, status)
            try:
                while not stop.is_set():
                    delay = cfg.poll_seconds
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
                    status["last_cycle"] = time.time()
                    status["jobs"] = dict(Counter(j["state"] for j in store.jobs()))
                    if args.once:
                        break
                    stop.wait(delay)
            finally:
                server.shutdown()
                server.server_close()
        finally:
            store.close()


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError) as exc:
        # Only these application-generated messages are safe to show. Model and HTTP
        # exceptions inside the worker are reduced to types before reaching logs.
        raise SystemExit(str(exc)) from None
