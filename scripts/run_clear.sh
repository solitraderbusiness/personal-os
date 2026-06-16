#!/usr/bin/env bash
# Headless cron wrapper for the daily session-buffer clear (runs ~04:00 instance-local).
# Clears every short-term context buffer; long-term memory is untouched.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$HERE"
export HOME="${HOME:-/root}"
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:${PATH:-}"

echo "=== daily session clear $(date -Is) ==="
exec "$HERE/venv/bin/python" -m scripts.sessions clear-all
