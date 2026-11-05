import time
from dataclasses import dataclass, field

from .agent import PROMPT, InvestigatorError, issue_payload, sources_payload

# Room for the system prompt, tool definitions and file-tool framing that Hermes adds per request.
REQUEST_OVERHEAD = 2500
OUTPUT_ALLOWANCE = 1500
COOLDOWNS = {"quota": 900, "auth": 86400, "unavailable": 300}


def estimate_tokens(text):
    """Deliberately pessimistic: about three bytes per token for code and JSON."""
    return (len(text.encode("utf-8")) + 2) // 3


def request_estimate(issue, commit, files):
    """Tokens for one model request that has read the whole snapshot."""
    context = issue_payload(issue) + sources_payload(commit, files)
    return REQUEST_OVERHEAD + estimate_tokens(PROMPT) + estimate_tokens(context) + OUTPUT_ALLOWANCE


class QuotaExhausted(RuntimeError):
    def __init__(self, retry_at, attempts):
        super().__init__("Every configured provider is cooling down or out of budget")
        self.retry_at = retry_at
        self.attempts = attempts


class ContextTooLarge(ValueError):
    def __init__(self, attempts):
        super().__init__("No configured provider accepts this much context; select fewer or smaller files")
        self.attempts = attempts


@dataclass
class InvestigationResult:
    report: dict
    provider: str
    model: str
    seconds: float
    reserved_tokens: int
    attempts: list = field(default_factory=list)


class ProviderRouter:
    """Tries providers in order, reserving a worst-case budget before each real run."""
    def __init__(self, cfg, store, runner, purpose="serve"):
        self.cfg, self.store, self.runner, self.purpose = cfg, store, runner, purpose

    def investigate(self, issue, commit, files):
        per_request = request_estimate(issue, commit, files)
        attempts, retry_at, saw_capacity = [], None, False
        for spec in self.cfg.routes:
            now = time.time()
            ceiling = min(x for x in (spec.max_input_tokens, spec.tpm, 10**9) if x)
            if per_request > ceiling:
                attempts.append({"provider": spec.name, "outcome": "too_large", "estimate": per_request})
                continue
            saw_capacity = True
            until = self.store.cooldown_until(spec.name)
            if until > now:
                attempts.append({"provider": spec.name, "outcome": "cooling_down"})
                retry_at = until if retry_at is None else min(retry_at, until)
                continue
            requests, tokens = spec.turns, spec.turns * per_request
            try:
                wait = self.store.reserve_usage(spec, requests, tokens, self.purpose)
            except ValueError:
                attempts.append({"provider": spec.name, "outcome": "too_large", "estimate": tokens})
                continue
            if wait:
                attempts.append({"provider": spec.name, "outcome": "budget_wait", "seconds": wait})
                retry_at = now + wait if retry_at is None else min(retry_at, now + wait)
                continue
            started = time.time()
            try:
                report = self.runner.investigate(issue, commit, files, spec)
            except InvestigatorError as exc:
                attempts.append({"provider": spec.name, "outcome": exc.category})
                if exc.category == "too_large":
                    continue
                if exc.category in COOLDOWNS:
                    until = time.time() + (exc.retry_after or COOLDOWNS[exc.category])
                    self.store.set_cooldown(spec.name, until, exc.category)
                    retry_at = until if retry_at is None else min(retry_at, until)
                    continue
                raise
            attempts.append({"provider": spec.name, "outcome": "ok"})
            return InvestigationResult(report, spec.name, spec.model, round(time.time() - started, 1), tokens, attempts)
        if retry_at is None or not saw_capacity:
            raise ContextTooLarge(attempts)
        raise QuotaExhausted(retry_at, attempts)
