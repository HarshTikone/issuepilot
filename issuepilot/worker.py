import hashlib
import json
import logging
import time

from .agent import check_secrets, render_report
from .github import GitHubError
from .providers import OUTPUT_ALLOWANCE, REQUEST_OVERHEAD, InvestigationResult, QuotaExhausted
from .retrieval import BlobCache, select_context

LOG = logging.getLogger("issuepilot")


def marker_for(repo, number):
    digest = hashlib.sha256(f"{repo.lower()}:{int(number)}:v1".encode()).hexdigest()[:24]
    return "<!-- issuepilot:" + digest + " -->"


def eligible(cfg, issue):
    return (issue.get("state") == "open" and "pull_request" not in issue
            and issue.get("user", {}).get("login", "").lower() in {x.lower() for x in cfg.allowed_authors}
            and cfg.label in {x.get("name") for x in issue.get("labels", [])})


def context_budget(cfg):
    """Largest snapshot, in tokens, that at least one configured provider could accept."""
    best = 0
    for spec in cfg.routes:
        ceiling = min([x for x in (spec.max_input_tokens, spec.tpm) if x] or [0])
        if not ceiling:
            return 0
        best = max(best, ceiling - REQUEST_OVERHEAD - OUTPUT_ALLOWANCE - 1500)
    return max(best, 1)


class Worker:
    def __init__(self, cfg, store, github, agent, status=None):
        self.cfg, self.store, self.github, self.agent = cfg, store, github, agent
        self.status = status if status is not None else {}

    def discover(self):
        for issue in self.github.issues(self.cfg.label):
            if eligible(self.cfg, issue):
                self.store.enqueue(self.cfg.repo, issue)

    def gather(self, issue):
        if not self.cfg.retrieval:
            commit, files = self.github.context(self.cfg.branch, self.cfg.context_paths)
            return commit, files, [{"path": p, "score": None} for p in files]
        commit = self.github.head(self.cfg.branch)
        files, record = select_context(self.github, commit, issue, self.cfg.retrieval_max_files,
                                       BlobCache(self.cfg.data_dir / "blobs"), self.cfg.context_paths,
                                       context_budget(self.cfg))
        return commit, files, record

    def process_one(self):
        job = self.store.next_job()
        if job is None:
            return False
        repo, number = job["repo"], job["number"]
        if repo != self.cfg.repo:
            raise ValueError("Data directory belongs to a different repository")
        marker = marker_for(repo, number)
        attempt = job["attempts"] + 1
        self.status["current_issue"] = number
        self.store.update(repo, number, state="running", attempts=attempt)
        try:
            # Recover ambiguous POST outcomes before spending more model calls.
            existing = self.github.find_report(number, marker)
            if existing:
                self.store.update(repo, number, state="succeeded", comment_url=existing, error=None)
                return True
            if job["attempts"] >= self.cfg.max_attempts:
                self.store.update(repo, number, state="failed", error="Attempt limit reached after recovery")
                return True
            issue = self.github.issue(number)
            if not eligible(self.cfg, issue):
                self.store.update(repo, number, state="cancelled", error="Issue is closed, unlabelled or not allowlisted")
                return True
            body = job["report"]
            source_issue = json.loads(job["issue"]) if body else issue
            if body is None:
                if not self.store.reserve_start(self.cfg.max_jobs_per_day):
                    self.store.update(repo, number, state="queued", attempts=job["attempts"], next_at=time.time() + 3600,
                                      error="Rolling 24-hour model-run limit reached")
                    return True
                commit, files, record = self.gather(issue)
                try:
                    result = self.agent.investigate(issue, commit, files)
                except QuotaExhausted as exc:
                    # Waiting for a quota reset is not a failed attempt.
                    self.store.update(repo, number, state="queued", attempts=job["attempts"], next_at=exc.retry_at,
                                      error="Waiting for provider quota", attempt_log=json.dumps(exc.attempts))
                    LOG.info("issue=%s state=waiting_for_quota", number)
                    return True
                if not isinstance(result, InvestigationResult):
                    result = InvestigationResult(result, "", "", 0, 0)
                body = render_report(repo, number, commit, result.report, marker)
                # Persist BEFORE the external write, so retries never need to regenerate it.
                self.store.update(repo, number, report=body, issue=json.dumps(issue), provider=result.provider,
                                  model=result.model, context=json.dumps(record),
                                  attempt_log=json.dumps(result.attempts))
            check_secrets(body, self.github.secrets() if hasattr(self.github, "secrets") else [])
            # Recheck permission to work after a potentially long model call.
            latest = self.github.issue(number)
            if (not eligible(self.cfg, latest) or any(latest.get(k) != source_issue.get(k) for k in ("title", "body"))):
                self.store.update(repo, number, state="cancelled", report=None,
                                  error="Issue withdrawn or edited before reporting; retry to investigate again")
                return True
            self.store.update(repo, number, state="reporting")
            url = self.github.find_report(number, marker) or self.github.post_report(number, body)
            self.store.update(repo, number, state="succeeded", comment_url=url, error=None)
            self.status["last_task_ok"] = time.time()
            LOG.info("issue=%s state=succeeded", number)
        except Exception as exc:
            # Never log raw HTTP bodies, model output, issue text or exception contents.
            failure = type(exc).__name__
            category = getattr(exc, "category", "")
            delay = min(3600, 30 * 2 ** (attempt - 1))
            if isinstance(exc, GitHubError):
                delay = max(delay, exc.retry_after)
            state = "failed" if attempt >= self.cfg.max_attempts else "queued"
            self.store.update(repo, number, state=state, next_at=time.time() + delay,
                              error=failure + (":" + category if category else ""),
                              attempt_log=json.dumps(getattr(exc, "attempts", []) or None))
            LOG.warning("issue=%s state=%s error_type=%s", number, state, failure)
        finally:
            self.status["current_issue"] = None
        return True
