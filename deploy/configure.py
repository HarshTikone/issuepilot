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


def secret(prompt):
    value = getpass.getpass(prompt).strip()
    if value and not re.fullmatch(r"[A-Za-z0-9_.-]{16,}", value):
        raise SystemExit("Unexpected key format. Nothing was written.")
    return value


def number(prompt):
    value = input(prompt).strip()
    if not value.isdigit():
        raise SystemExit("A numeric ID is required. Nothing was written.")
    return int(value)


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
    root = Path(__file__).resolve().parents[1]
    cfg = json.loads((root / "config.example.json").read_text())

    print("Model keys: leave a prompt empty to skip that provider. At least one is required.")
    keys = {"GEMINI_API_KEY": secret("Google AI Studio (Gemini) API key (hidden): "),
            "GROQ_API_KEY": secret("Groq API key (hidden): ")}
    keys = {name: value for name, value in keys.items() if value}
    if not keys:
        raise SystemExit("No model key entered. Nothing was written.")
    cfg["providers"] = [p for p in cfg["providers"] if p["key_env"] in keys]
    for spec in cfg["providers"]:
        model = input(f"Model ID for {spec['name']} [{spec['model']}]: ").strip() or spec["model"]
        if any(c.isspace() for c in model):
            raise SystemExit("A model ID without spaces is required")
        spec["model"] = model
    cfg["provider"], cfg["model"] = cfg["providers"][0]["name"], cfg["providers"][0]["model"]

    mode = input("GitHub identity: [a]pp bot (recommended) or [t]oken? ").strip().lower()[:1]
    service = ""
    if mode == "a":
        key_file = directory / "app.pem"
        if not key_file.is_file():
            raise SystemExit(f"Copy the App's private key to {key_file} first (chmod 640, group issuepilot)")
        cfg.update(auth="app", app_id=number("GitHub App ID: "), installation_id=number("Installation ID: "),
                   app_key_file=str(key_file))
    else:
        token = secret("GitHub fine-grained token (hidden): ")
        if not token:
            raise SystemExit("A token is required for token mode. Nothing was written.")
        service = "GITHUB_TOKEN=" + token + "\n"

    cfg.update(hermes_image=image, data_dir="/var/lib/issuepilot", provider_env_file="/etc/issuepilot/provider.env")
    write_private(directory / "config.json", json.dumps(cfg, indent=2) + "\n", True)
    write_private(directory / "provider.env", "".join(f"{k}={v}\n" for k, v in keys.items()), True)
    write_private(directory / "service.env", service)
    print("Configuration saved privately. Image digest pinned. No service was started.")


if __name__ == "__main__":
    main()
