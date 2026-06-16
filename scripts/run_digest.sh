#!/usr/bin/env bash
# Headless cron wrapper for the daily digest. Sets a sane PATH/HOME (cron's env is
# minimal) so the `claude` CLI and its auth are found, then runs the digest. Stdout/
# stderr are captured by install_cron.sh into generated/digest-cron.log.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # repo root
cd "$HERE"

export HOME="${HOME:-/root}"
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:${PATH:-}"

echo "=== digest run $(date -Is) ==="
exec "$HERE/venv/bin/python" -m scripts.digest --date today --push
