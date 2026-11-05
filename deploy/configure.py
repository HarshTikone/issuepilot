"""Run interactively as root on the dedicated VPS. Secrets never enter shell history."""
import getpass
import json
import os
import re
import shutil
import subprocess
from pathlib import Path


def write_private(path, content, group_read=False):
    path = Path(path)
    if path.exists():
        raise SystemExit(f"{path} already exists. Edit it deliberately; this wizard does not overwrite configuration.")
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o640 if group_read else 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(content)
    path.chmod(0o640 if group_read else 0o600)
    shutil.chown(path, user="root", group="issuepilot")


def main():
    if not hasattr(os, "geteuid") or os.geteuid() != 0:
        raise SystemExit("Run this on the Ubuntu server with sudo after install-service.sh")
    directory = Path("/etc/issuepilot")
    if not directory.is_dir():
        raise SystemExit("Run install-service.sh first")
    if any((directory / name).exists() for name in ("config.json", "provider.env", "service.env")):
        raise SystemExit("Configuration files already exist. Edit them deliberately rather than overwriting.")
    image = subprocess.check_output(["docker", "image", "inspect", "nousresearch/hermes-agent:stable",
                                     "--format", "{{index .RepoDigests 0}}"], text=True).strip()
    if not re.fullmatch(r"nousresearch/hermes-agent@sha256:[a-f0-9]{64}", image):
        raise SystemExit("Pull the official stable Hermes image first")
    model = input("Tool-capable OpenRouter model ID (copy the exact ID from your provider): ").strip()
    if not model or any(c.isspace() for c in model):
        raise SystemExit("A model ID without spaces is required")
    github = getpass.getpass("GitHub fine-grained token (hidden): ").strip()
    provider = getpass.getpass("OpenRouter API key (hidden): ").strip()
    if not all(re.fullmatch(r"[A-Za-z0-9_-]{16,}", value) for value in (github, provider)):
        raise SystemExit("Unexpected key format. Nothing was written.")
    root = Path(__file__).resolve().parents[1]
    cfg = json.loads((root / "config.example.json").read_text())
    cfg.update(hermes_image=image, model=model, data_dir="/var/lib/issuepilot",
               provider_env_file="/etc/issuepilot/provider.env")
    write_private(directory / "config.json", json.dumps(cfg, indent=2) + "\n", True)
    write_private(directory / "provider.env", "OPENROUTER_API_KEY=" + provider + "\n", True)
    write_private(directory / "service.env", "GITHUB_TOKEN=" + github + "\n")
    print("Configuration saved privately. Image digest pinned. No service was started.")


if __name__ == "__main__":
    main()
