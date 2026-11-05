import base64
import copy
import io
import json
import os
import subprocess
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from issuepilot.agent import HermesDocker, plain, prepare_input, render_report, validate_report
from issuepilot.config import Config, provider_secrets
from issuepilot.demo import ISSUE, fixture_report
from issuepilot.github import GitHub, GitHubError, NoRedirect
from issuepilot.health import handler_type
from issuepilot.store import ProcessLock, Store
from issuepilot.worker import Worker, eligible, marker_for

ROOT = Path(__file__).resolve().parents[1]
FILES = {"demo_app/discounts.py": (ROOT / "demo_app/discounts.py").read_text(encoding="utf-8")}


class FakeGitHub:
    def __init__(self):
        self.current = copy.deepcopy(ISSUE)
        self.comments = []
        self.ambiguous = False
        self.read_failure = False

    def issues(self, label):
        return [copy.deepcopy(self.current)]

    def issue(self, number):
        if self.read_failure:
            raise GitHubError(403, 120)
        return copy.deepcopy(self.current)

    def context(self, branch, paths):
        return "a" * 40, FILES

    def find_report(self, number, marker):
        return "https://github.com/HarshTikone/issuepilot/issues/1#issuecomment-1" if self.comments else None

    def post_report(self, number, body):
        self.comments.append(body)
        if self.ambiguous:
            self.ambiguous = False
            raise GitHubError(0)
        return self.find_report(number, "")


class FakeAgent:
    def __init__(self):
        self.calls = 0
        self.fail = False
        self.during_run = None

    def investigate(self, *args):
        self.calls += 1
        if self.fail:
            raise RuntimeError("sensitive stderr must never be persisted")
        if self.during_run:
            self.during_run()
        return fixture_report()


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = replace(Config.load(ROOT / "config.example.json"), data_dir=Path(self.tmp.name))
        self.path = self.cfg.data_dir / "jobs.sqlite3"
        self.store = Store(self.path)
        self.github, self.agent = FakeGitHub(), FakeAgent()
        self.worker = Worker(self.cfg, self.store, self.github, self.agent)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def job(self):
        return self.store.jobs()[0]

    def ready_retry(self):
        self.store.update(self.cfg.repo, 1, next_at=0)

    def test_full_task_ends_in_one_source_linked_comment(self):
        self.worker.discover()
        self.worker.process_one()
        self.assertEqual(self.job()["state"], "succeeded")
        self.assertIn("/blob/" + "a" * 40, self.github.comments[0])
        self.assertIn("not executed", self.github.comments[0])

    def test_repeated_discovery_does_not_repeat_work(self):
        for _ in range(3):
            self.worker.discover()
            self.worker.process_one()
        self.assertEqual(self.agent.calls, 1)
        self.assertEqual(len(self.github.comments), 1)

    def test_untrusted_author_is_ignored(self):
        self.github.current["user"]["login"] = "outsider"
        self.worker.discover()
        self.assertEqual(self.store.jobs(), [])

    def test_pull_request_is_ignored(self):
        self.github.current["pull_request"] = {}
        self.worker.discover()
        self.assertEqual(self.store.jobs(), [])

    def test_withdrawn_label_cancels_queued_job(self):
        self.worker.discover()
        self.github.current["labels"] = []
        self.worker.process_one()
        self.assertEqual(self.job()["state"], "cancelled")
        self.assertEqual(self.agent.calls, 0)

    def test_issue_edited_during_run_does_not_receive_stale_report(self):
        self.worker.discover()
        self.agent.during_run = lambda: self.github.current.update(body="Changed requirements")
        self.worker.process_one()
        self.assertEqual(self.job()["state"], "cancelled")
        self.assertIsNone(self.job()["report"])
        self.assertEqual(self.github.comments, [])

    def test_closed_during_run_cancels_publication(self):
        self.worker.discover()
        self.agent.during_run = lambda: self.github.current.update(state="closed")
        self.worker.process_one()
        self.assertEqual(self.job()["state"], "cancelled")
        self.assertEqual(self.github.comments, [])

    def test_ambiguous_post_reconciles_without_second_model_run(self):
        self.github.ambiguous = True
        self.worker.discover()
        self.worker.process_one()
        self.assertEqual(self.job()["state"], "queued")
        self.ready_retry()
        self.worker.process_one()
        self.assertEqual(self.job()["state"], "succeeded")
        self.assertEqual(self.agent.calls, 1)
        self.assertEqual(len(self.github.comments), 1)

    def test_report_survives_crash_between_persist_and_post(self):
        self.worker.discover()
        body = "persisted report"
        self.store.update(self.cfg.repo, 1, state="reporting", report=body)
        self.store.close()
        self.store = Store(self.path)
        self.store.recover()
        Worker(self.cfg, self.store, self.github, self.agent).process_one()
        self.assertEqual(self.github.comments, [body])
        self.assertEqual(self.agent.calls, 0)

    def test_failures_have_backoff_and_are_bounded(self):
        self.agent.fail = True
        self.worker.discover()
        for _ in range(3):
            self.ready_retry()
            self.worker.process_one()
        self.assertEqual(self.job()["state"], "failed")
        self.assertEqual(self.agent.calls, 3)
        self.assertEqual(self.job()["error"], "RuntimeError")
        self.assertNotIn("sensitive", json.dumps(self.store.jobs()))
        self.assertFalse(self.worker.process_one())

    def test_recovery_does_not_bypass_attempt_limit(self):
        self.worker.discover()
        self.store.update(self.cfg.repo, 1, attempts=3, state="running")
        self.store.recover()
        self.worker.process_one()
        self.assertEqual(self.job()["state"], "failed")
        self.assertEqual(self.agent.calls, 0)

    def test_rolling_budget_survives_store_reopen(self):
        self.assertTrue(self.store.reserve_start(1))
        self.store.close()
        self.store = Store(self.path)
        self.assertFalse(self.store.reserve_start(1))

    def test_budget_exhaustion_defers_without_spending_attempt(self):
        self.cfg = replace(self.cfg, max_jobs_per_day=1)
        self.store.reserve_start(1)
        worker = Worker(self.cfg, self.store, self.github, self.agent)
        worker.discover()
        worker.process_one()
        self.assertEqual(self.job()["state"], "queued")
        self.assertEqual(self.job()["attempts"], 0)
        self.assertEqual(self.agent.calls, 0)

    def test_rate_limit_honors_retry_delay(self):
        self.worker.discover()
        self.github.read_failure = True
        self.worker.process_one()
        self.assertGreaterEqual(self.job()["next_at"] - self.job()["updated_at"], 119)
        self.assertEqual(self.agent.calls, 0)

    def test_retry_only_accepts_failed_or_cancelled_jobs(self):
        self.worker.discover()
        with self.assertRaises(ValueError):
            self.store.retry(self.cfg.repo, 1)
        self.store.update(self.cfg.repo, 1, state="failed")
        self.store.retry(self.cfg.repo, 1)
        self.assertEqual(self.job()["attempts"], 0)


class ReportTests(unittest.TestCase):
    def check_bad(self, report):
        with self.assertRaises((ValueError, TypeError)):
            validate_report(json.dumps(report), FILES)

    def test_valid_report_passes(self):
        self.assertEqual(validate_report(json.dumps(fixture_report()), FILES)["category"], "bug")

    def test_unknown_file_rejected(self):
        report = fixture_report()
        report["evidence"][0]["path"] = "../../etc/passwd"
        self.check_bad(report)

    def test_nonexistent_or_boolean_line_rejected(self):
        for line in (99, 0, -1, True, "4"):
            report = fixture_report()
            report["evidence"][0]["line_start"] = line
            self.check_bad(report)

    def test_missing_fields_or_empty_evidence_rejected(self):
        report = fixture_report()
        del report["summary"]
        self.check_bad(report)
        report = fixture_report()
        report["evidence"] = []
        self.check_bad(report)

    def test_extra_fields_and_oversized_report_rejected(self):
        report = fixture_report()
        report["command"] = "execute something"
        self.check_bad(report)
        with self.assertRaises(ValueError):
            validate_report("x" * 24001, FILES)

    def test_noisy_or_fenced_output_fails_closed(self):
        for prefix in ("Here is the result:", "```json\n"):
            with self.assertRaises(ValueError):
                validate_report(prefix + json.dumps(fixture_report()), FILES)

    def test_exact_secret_or_token_pattern_blocks_publication(self):
        for secret, known in (("private-key-value-1234", ["private-key-value-1234"]),
                              ("github_pat_1234567890abcdefghijkl", [])):
            report = fixture_report()
            report["summary"] = secret
            with self.assertRaises(ValueError):
                validate_report(json.dumps(report), FILES, known)

    def test_unicode_escape_cannot_hide_exact_credential(self):
        report = fixture_report()
        report["summary"] = "private-key-value-1234"
        raw = json.dumps(report).replace("private", "\\u0070rivate")
        with self.assertRaises(ValueError):
            validate_report(raw, FILES, ["private-key-value-1234"])

    def test_markup_and_mentions_are_neutralized(self):
        value = plain("@everyone <script>alert(1)</script> [click](https://evil.invalid)")
        self.assertNotIn("@everyone", value)
        self.assertNotIn("<script>", value)
        self.assertNotIn("[click]", value)

    def test_marker_is_stable_and_repository_specific(self):
        self.assertEqual(marker_for("HarshTikone/issuepilot", 1), marker_for("harshtikone/issuepilot", 1))
        self.assertNotEqual(marker_for("x/y", 1), marker_for("x/y", 2))


class BoundariesTests(unittest.TestCase):
    def test_configuration_rejects_unsafe_paths(self):
        base = Config.load(ROOT / "config.example.json")
        for path in ("../secret", "/etc/passwd", ".env", "keys/id.pem", "C:\\secret"):
            with self.assertRaises(ValueError):
                replace(base, context_paths=(path,)).validate()

    def test_live_configuration_requires_digest(self):
        with self.assertRaisesRegex(ValueError, "digest"):
            Config.load(ROOT / "config.example.json").validate_live()

    def test_process_lock_excludes_second_worker(self):
        with tempfile.TemporaryDirectory() as directory:
            with ProcessLock(Path(directory) / "lock"):
                with self.assertRaises(RuntimeError):
                    with ProcessLock(Path(directory) / "lock"):
                        pass

    def test_provider_env_rejects_github_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "provider.env"
            path.write_text("GITHUB_TOKEN=not-allowed", encoding="utf-8")
            with self.assertRaises(ValueError):
                provider_secrets(path)

    def test_docker_has_no_host_control_mount_or_github_token(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "provider.env"
            path.write_text("OPENROUTER_API_KEY=secret-model-key", encoding="utf-8")
            cfg = replace(Config.load(ROOT / "config.example.json"), provider_env_file=path)
            args = HermesDocker(cfg).command(directory, "issuepilot-job-test")
            command = " ".join(args)
            self.assertNotIn("secret-model-key", command)
            self.assertNotIn("GITHUB_TOKEN", command)
            self.assertNotIn("docker.sock", command)
            self.assertIn("--read-only", args)
            self.assertIn("--safe-mode", args)
            self.assertIn("10000:10000", args)
            self.assertEqual(args[args.index("--toolsets") + 1], "file")

    def test_input_contains_numbered_source_and_not_prompt_interpolation(self):
        with tempfile.TemporaryDirectory() as directory:
            issue = copy.deepcopy(ISSUE)
            issue["body"] = '$(echo secret) `injection` "quotes"'
            prepare_input(directory, issue, "a" * 40, FILES)
            self.assertEqual(json.loads((Path(directory) / "issue.json").read_text())["body"], issue["body"])
            sources = json.loads((Path(directory) / "sources.json").read_text())
            self.assertEqual(sources["files"]["demo_app/discounts.py"][3]["line"], 4)

    def test_container_removed_on_timeout(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "provider.env"
            path.write_text("OPENROUTER_API_KEY=secret-model-key", encoding="utf-8")
            cfg = replace(Config.load(ROOT / "config.example.json"), provider_env_file=path, data_dir=Path(directory))
            process = Mock()
            process.wait.side_effect = [subprocess.TimeoutExpired("docker", 240), 0]
            process.poll.return_value = None
            with patch("issuepilot.agent.subprocess.Popen", return_value=process), patch("issuepilot.agent.subprocess.run") as run:
                with self.assertRaises(subprocess.TimeoutExpired):
                    HermesDocker(cfg).investigate(ISSUE, "a" * 40, FILES)
                self.assertEqual(run.call_args.args[0][:3], ["docker", "rm", "-f"])
                process.kill.assert_called_once()


class GitHubTests(unittest.TestCase):
    def test_pagination_collects_all_pages(self):
        github = GitHub("owner/repo", "secret")
        github.request = Mock(side_effect=[[{}] * 100, [{"number": 101}]])
        self.assertEqual(len(github.pages("/path")), 101)
        self.assertIn("page=2", github.request.call_args.args[0])

    def test_pagination_cap_fails_instead_of_dropping_work(self):
        github = GitHub("owner/repo", "secret")
        github.request = Mock(return_value=[{}] * 100)
        with self.assertRaisesRegex(ValueError, "Pagination"):
            github.pages("/path")

    def test_forged_marker_from_other_actor_does_not_suppress_task(self):
        github = GitHub("owner/repo", "secret")
        github.actor_id = 7
        github.pages = Mock(return_value=[{"body": "marker", "user": {"id": 9}, "html_url": "forged"}])
        self.assertIsNone(github.find_report(1, "marker"))

    def test_existing_comment_requires_authenticated_actor(self):
        github = GitHub("owner/repo", "secret")
        github.request = Mock(return_value={"id": 7})
        github.pages = Mock(return_value=[{"body": "marker", "user": {"id": 7}, "html_url": "real"}])
        self.assertEqual(github.find_report(1, "marker"), "real")

    def test_source_context_uses_one_immutable_revision(self):
        github = GitHub("owner/repo", "secret")
        github.request = Mock(side_effect=[{"sha": "a" * 40},
            {"type": "file", "encoding": "base64", "size": 5, "content": base64.b64encode(b"hello").decode()}])
        commit, files = github.context("main", ["src/code.py"])
        self.assertEqual(files, {"src/code.py": "hello"})
        self.assertIn("ref=" + commit, github.request.call_args.args[0])

    def test_http_error_never_exposes_request_credentials(self):
        opener = Mock()
        opener.open.side_effect = HTTPError("https://api.github.com", 401, "sensitive", {}, None)
        with self.assertRaises(GitHubError) as context:
            GitHub("owner/repo", "very-secret-token", opener).request("/user")
        self.assertNotIn("very-secret-token", str(context.exception))
        self.assertNotIn("sensitive", str(context.exception))

    def test_redirects_are_not_followed_with_authorization(self):
        self.assertIsNone(NoRedirect().redirect_request(None, None, None, None, None, None))


class HealthTests(unittest.TestCase):
    def test_liveness_readiness_and_staleness_are_distinct(self):
        status = {"last_poll_ok": False, "last_cycle": 0}
        class Connection:
            def __init__(self, path):
                self.request = io.BytesIO(f"GET {path} HTTP/1.0\r\nHost: localhost\r\n\r\n".encode())
                self.output = bytearray()
            def makefile(self, *args):
                return self.request
            def sendall(self, data):
                self.output.extend(data)
        def request(path):
            connection = Connection(path)
            handler_type(status, 60)(connection, ("127.0.0.1", 1234), None)
            headers, body = bytes(connection.output).split(b"\r\n\r\n", 1)
            return int(headers.split()[1]), json.loads(body)
        self.assertEqual(request("/healthz")[0], 200)
        self.assertEqual(request("/readyz")[0], 503)
        status.update(last_poll_ok=True, last_cycle=time.time())
        code, body = request("/readyz")
        self.assertEqual(code, 200)
        self.assertTrue(body["ready"])
        status["last_cycle"] = time.time() - 61
        self.assertEqual(request("/readyz")[0], 503)


if __name__ == "__main__":
    unittest.main()
