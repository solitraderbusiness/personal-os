#!/usr/bin/env bash
# Headless cron wrapper for the reminders tick. Runs every ~10 min; pushes any due
# reminders to Telegram and marks them notified (idempotent). Minimal cron env, so set
# a sane PATH/HOME for the `claude` CLI auth (not needed here, but kept consistent).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$HERE"
export HOME="${HOME:-/root}"
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:${PATH:-}"

exec "$HERE/venv/bin/python" -m scripts.reminders check
