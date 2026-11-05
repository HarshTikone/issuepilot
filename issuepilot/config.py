import json
import os
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


@dataclass(frozen=True)
class Config:
    repo: str
    branch: str
    label: str
    allowed_authors: tuple
    context_paths: tuple
    data_dir: Path
    hermes_image: str
    provider: str
    model: str
    provider_env_file: Path
    poll_seconds: int = 60
    timeout_seconds: int = 240
    max_attempts: int = 3
    max_jobs_per_day: int = 10
    health_port: int = 8787

    @classmethod
    def load(cls, path):
        path = Path(path).resolve()
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        for key in ("data_dir", "provider_env_file"):
            p = Path(raw[key]).expanduser()
            raw[key] = p.resolve() if p.is_absolute() else (path.parent / p).resolve()
        for key in ("allowed_authors", "context_paths"):
            raw[key] = tuple(raw[key])
        cfg = cls(**raw)
        cfg.validate()
        return cfg

    def validate(self):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", self.repo):
            raise ValueError("repo must be OWNER/REPOSITORY")
        if not self.allowed_authors or not all(re.fullmatch(r"[A-Za-z0-9-]+", x) for x in self.allowed_authors):
            raise ValueError("Specify at least one allowed GitHub issue author")
        if not self.branch or not self.label or not self.model or not self.provider:
            raise ValueError("branch, label, model and provider are required")
        if not 1 <= len(self.context_paths) <= 12:
            raise ValueError("Choose 1 to 12 small source files for context")
        for value in self.context_paths:
            p = PurePosixPath(value)
            if p.is_absolute() or ".." in p.parts or "\\" in value or ":" in value or not p.parts:
                raise ValueError("context_paths must be relative repository file paths")
            if any(part.startswith(".") for part in p.parts) or p.suffix.lower() in (".pem", ".key"):
                raise ValueError("Hidden files and key files cannot be source context")
        for key, low, high in (("poll_seconds", 15, 3600), ("timeout_seconds", 30, 600),
                               ("max_attempts", 1, 5), ("max_jobs_per_day", 1, 100),
                               ("health_port", 1024, 65535)):
            value = getattr(self, key)
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"{key} must be an integer between {low} and {high}")

    def validate_live(self):
        if not re.fullmatch(r"nousresearch/hermes-agent@sha256:[a-f0-9]{64}", self.hermes_image):
            raise ValueError("Pin the official Hermes image by digest; see docs/DEPLOYMENT.md")
        if not os.environ.get("GITHUB_TOKEN"):
            raise ValueError("GITHUB_TOKEN is missing; configure the service environment")
        if not self.provider_env_file.is_file():
            raise ValueError("Provider environment file is missing")


def provider_secrets(path):
    """Small Docker env-file subset: API keys only, never supervisor credentials."""
    result = {}
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if not sep or not re.fullmatch(r"[A-Z][A-Z0-9_]*_API_KEY", key) or not value or value != value.strip():
            raise ValueError("Provider file must contain unquoted NAME_API_KEY=value entries only")
        result[key] = value
    if not result:
        raise ValueError("Provider environment file has no API key")
    return result
