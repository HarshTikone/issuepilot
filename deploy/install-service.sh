#!/usr/bin/env bash
set -euo pipefail
if [ "$(id -u)" -ne 0 ]; then
  echo 'Run with sudo on the Ubuntu server.' >&2
  exit 1
fi
task_root="$(cd "$(dirname "$0")/.." && pwd)"
if [ "$task_root" != /opt/issuepilot ]; then
  echo 'Clone this repository to /opt/issuepilot first.' >&2
  exit 1
fi
command -v docker >/dev/null || { echo 'Install Docker Engine first; see docs/DEPLOYMENT.md.' >&2; exit 1; }
id issuepilot >/dev/null 2>&1 || useradd --system --create-home --home-dir /var/lib/issuepilot --shell /usr/sbin/nologin issuepilot
usermod -aG docker issuepilot
install -d -o root -g issuepilot -m 0750 /etc/issuepilot
# Input directory needs execute permission for Docker's unprivileged task UID.
# Only curated issue/source snapshots go under inputs; SQLite remains private.
install -d -o issuepilot -g issuepilot -m 0711 /var/lib/issuepilot
install -d -o issuepilot -g issuepilot -m 0711 /var/lib/issuepilot/inputs
install -m 0644 deploy/issuepilot.service /etc/systemd/system/issuepilot.service
systemctl daemon-reload
echo 'Service installed but not started. Next: sudo python3 deploy/configure.py'
