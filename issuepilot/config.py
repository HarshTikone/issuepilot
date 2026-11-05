import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

PROVIDER_FIELDS = {"name", "hermes_provider", "model", "key_env", "base_url", "rpm", "rpd", "tpm", "tpd",
                   "max_input_tokens", "max_turns"}
# Assumed turns for reservations when the max-turns flag is disabled for an image.
DEFAULT_TURNS = 8


@dataclass(frozen=True)
class ProviderSpec:
    """One inference route. Zero for a limit means the provider publishes none we enforce."""
    name: str
    hermes_provider: str
    model: str
    key_env: str = ""
    base_url: str = ""
    rpm: int = 0
    rpd: int = 0
    tpm: int = 0
    tpd: int = 0
    max_input_tokens: int = 0
    max_turns: int = 6

    @property
    def turns(self):
        return self.max_turns or DEFAULT_TURNS

    def validate(self):
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,31}", self.name):
            raise ValueError("Provider name must be short lowercase text")
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,31}", self.hermes_provider):
            raise ValueError("hermes_provider must be a Hermes provider name such as gemini or custom")
        if not self.model or any(c.isspace() for c in self.model):
            raise ValueError("Each provider needs a model ID without spaces")
        if self.key_env and not re.fullmatch(r"[A-Z][A-Z0-9_]*_API_KEY", self.key_env):
            raise ValueError("key_env must name a NAME_API_KEY entry in the provider file")
        if self.base_url and not re.fullmatch(r"https://[A-Za-z0-9.-]+(?::\d+)?(?:/[A-Za-z0-9._~/-]*)?", self.base_url):
            raise ValueError("base_url must be a plain https URL")
        if self.base_url and (self.hermes_provider != "custom" or not self.key_env):
            raise ValueError("A base_url needs hermes_provider 'custom' and a key_env")
        for key in ("rpm", "rpd", "tpm", "tpd", "max_input_tokens"):
            value = getattr(self, key)
            if type(value) is not int or not 0 <= value <= 100_000_000:
                raise ValueError(f"Provider {key} must be a non-negative integer")
        if type(self.max_turns) is not int or not 0 <= self.max_turns <= 30:
            raise ValueError("max_turns must be between 0 (omit the flag) and 30")


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
    providers: tuple = field(default=())
    retrieval: bool = False
    retrieval_max_files: int = 6
    auth: str = "token"
    app_id: int = 0
    installation_id: int = 0
    app_key_file: str = ""
    heartbeat_url: str = ""

    @classmethod
    def load(cls, path):
        path = Path(path).resolve()
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        for key in ("data_dir", "provider_env_file"):
            p = Path(raw[key]).expanduser()
            raw[key] = p.resolve() if p.is_absolute() else (path.parent / p).resolve()
        for key in ("allowed_authors", "context_paths"):
            raw[key] = tuple(raw.get(key) or ())
        specs = []
        for item in raw.get("providers") or ():
            if not isinstance(item, dict) or set(item) - PROVIDER_FIELDS:
                raise ValueError("Unknown provider setting; see config.example.json")
            specs.append(ProviderSpec(**item))
        raw["providers"] = tuple(specs)
        cfg = cls(**raw)
        cfg.validate()
        return cfg

    @property
    def routes(self):
        """Configured providers, or the single legacy provider/model pair."""
        if self.providers:
            return self.providers
        return (ProviderSpec(name=self.provider, hermes_provider=self.provider, model=self.model),)

    def validate(self):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", self.repo):
            raise ValueError("repo must be OWNER/REPOSITORY")
        if not self.allowed_authors or not all(re.fullmatch(r"[A-Za-z0-9-]+", x) for x in self.allowed_authors):
            raise ValueError("Specify at least one allowed GitHub issue author")
        if not self.branch or not self.label or not self.model or not self.provider:
            raise ValueError("branch, label, model and provider are required")
        low = 0 if self.retrieval else 1
        if not low <= len(self.context_paths) <= 12:
            raise ValueError("Choose 1 to 12 small source files for context, or enable retrieval")
        for value in self.context_paths:
            check_repo_path(value)
        for key, low, high in (("poll_seconds", 15, 3600), ("timeout_seconds", 30, 600),
                               ("max_attempts", 1, 5), ("max_jobs_per_day", 1, 100),
                               ("health_port", 1024, 65535), ("retrieval_max_files", 1, 12)):
            value = getattr(self, key)
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"{key} must be an integer between {low} and {high}")
        names = [spec.name for spec in self.routes]
        if len(names) != len(set(names)):
            raise ValueError("Provider names must be unique")
        for spec in self.routes:
            spec.validate()
        if self.auth not in ("token", "app"):
            raise ValueError("auth must be 'token' or 'app'")
        if self.auth == "app" and not (self.app_id > 0 and self.installation_id > 0 and self.app_key_file):
            raise ValueError("GitHub App auth needs app_id, installation_id and app_key_file")
        if self.heartbeat_url and not re.fullmatch(r"https://[A-Za-z0-9.-]+/[A-Za-z0-9._~/-]+", self.heartbeat_url):
            raise ValueError("heartbeat_url must be a plain https URL")

    def validate_live(self):
        if not re.fullmatch(r"nousresearch/hermes-agent@sha256:[a-f0-9]{64}", self.hermes_image):
            raise ValueError("Pin the official Hermes image by digest; see docs/DEPLOYMENT.md")
        if self.auth == "token" and not os.environ.get("GITHUB_TOKEN"):
            raise ValueError("GITHUB_TOKEN is missing; configure the service environment")
        if self.auth == "app" and not Path(self.app_key_file).is_file():
            raise ValueError("GitHub App private key file is missing")
        if not self.provider_env_file.is_file():
            raise ValueError("Provider environment file is missing")
        keys = provider_secrets(self.provider_env_file)
        for spec in self.routes:
            if spec.key_env and spec.key_env not in keys:
                raise ValueError(f"Provider file has no {spec.key_env} for provider {spec.name}")


def check_repo_path(value):
    p = PurePosixPath(value)
    if p.is_absolute() or ".." in p.parts or "\\" in value or ":" in value or not p.parts:
        raise ValueError("context_paths must be relative repository file paths")
    if any(part.startswith(".") for part in p.parts) or p.suffix.lower() in (".pem", ".key"):
        raise ValueError("Hidden files and key files cannot be source context")


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
