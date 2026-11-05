#!/usr/bin/env bash
# Execute an administration command with the same environment as the service.
set -euo pipefail
if [ "$(id -u)" -ne 0 ]; then
  echo 'Use sudo for this helper.' >&2
  exit 1
fi
cd /opt/issuepilot
set -a
# Root-only file created by configure.py; never source issue or repository input.
source /etc/issuepilot/service.env
set +a
exec runuser --preserve-environment -u issuepilot -- /usr/bin/env HOME=/var/lib/issuepilot /usr/bin/python3 -m issuepilot --config /etc/issuepilot/config.json "$@"
