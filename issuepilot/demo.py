import json
import tempfile
from dataclasses import replace
from pathlib import Path

from .agent import render_report, validate_report
from .store import Store
from .worker import Worker, marker_for

ISSUE = {"number": 1, "title": "A zero-percent discount changes the total",
         "body": "Calling apply_discount(100, 0) should return 100, but returns 90. Investigate the cause and propose tests.",
         "state": "open", "user": {"login": "HarshTikone"}, "labels": [{"name": "agent-ready"}]}


def fixture_report():
    return {"outcome": "diagnosis", "summary": "A zero-percent discount is replaced with the default 10 percent because zero is falsy.",
            "category": "bug", "priority": "medium",
            "evidence": [{"path": "demo_app/discounts.py", "line_start": 4, "line_end": 5,
                          "finding": "The `or 10` expression replaces both None and 0 with 10. This suggests the reported behavior."}],
            "next_steps": ["Default to 10 only when percent is None, preserving an explicit zero."],
            "verification_steps": ["Assert apply_discount(100, 0) == 100.",
                                   "Assert apply_discount(100, None) == 90 and apply_discount(100, 20) == 80."],
            "assumptions": ["This is a demonstration fixture; no model or GitHub request was made."],
            "questions": []}


class DemoGitHub:
    def __init__(self, files):
        self.files, self.comments = files, []

    def issues(self, label):
        return [ISSUE]

    def issue(self, number):
        return ISSUE

    def context(self, branch, paths):
        return "0" * 40, self.files

    def find_report(self, number, marker):
        return "demo://comment/1" if self.comments else None

    def post_report(self, number, body):
        self.comments.append(body)
        return "demo://comment/1"


class DemoAgent:
    def investigate(self, issue, commit, files):
        return validate_report(json.dumps(fixture_report()), files)


def run_demo(root, output, cfg):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    files = {"demo_app/discounts.py": (root / "demo_app/discounts.py").read_text(encoding="utf-8")}
    cfg = replace(cfg, repo="HarshTikone/issuepilot", label="agent-ready", allowed_authors=("HarshTikone",))
    github = DemoGitHub(files)
    with tempfile.TemporaryDirectory() as temp:
        store = Store(Path(temp) / "demo.db")
        try:
            worker = Worker(cfg, store, github, DemoAgent())
            worker.discover()
            worker.process_one()
            worker.discover()
            worker.process_one()
            jobs = store.jobs()
            if jobs[0]["state"] != "succeeded" or len(github.comments) != 1:
                raise RuntimeError("Demo workflow failed")
        finally:
            store.close()
    report = render_report(cfg.repo, 1, "0" * 40, fixture_report(), marker_for(cfg.repo, 1), "SIMULATED DEMO")
    (output / "demo-report.md").write_text(report, encoding="utf-8")
    result = {"mode": "simulated", "real_hermes_run": False, "github_contacted": False,
              "linux_deployed": False, "jobs_completed": 1, "comments_simulated": len(github.comments),
              "duplicate_discovery_ignored": True}
    (output / "demo-result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result
