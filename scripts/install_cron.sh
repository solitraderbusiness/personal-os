#!/usr/bin/env bash
# Idempotently register (or remove) THIS instance's daily-digest cron job.
#
# Safety (design-review requirement): edits the crontab via `crontab -l` + a tagged
# marker block + `crontab -` — NEVER `crontab <file>` — so any unrelated cron lines
# (e.g. n8n-tether-watchdog) are preserved. Re-running replaces only this instance's
# block (no duplicates). The cron command is flock-wrapped so overlapping runs are
# skipped, not stacked.
#
# Usage:  scripts/install_cron.sh           # install/update this instance's job
#         scripts/install_cron.sh --remove  # remove only this instance's job
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$HERE"
PY="$HERE/venv/bin/python"
REMOVE=0
[ "${1:-}" = "--remove" ] && REMOVE=1

# Instance name.
NAME="$(PYTHONPATH="$HERE" "$PY" -c 'from scripts import config; print(config.instance_name())' 2>/dev/null || echo personal-os)"

# Cron runs in server (UTC) time, but digest/daily-clear are configured in the instance
# timezone — convert local HH:MM -> UTC cron fields. Output: "DIG_MIN DIG_HOUR CLR_MIN CLR_HOUR".
SCHED="$(PYTHONPATH="$HERE" "$PY" -c "
from scripts import config
from zoneinfo import ZoneInfo
from datetime import datetime, timezone
tz = ZoneInfo(config.timezone()); d = config.load_config()
def u(h, m):
    x = datetime(2026, 1, 1, int(h), int(m), tzinfo=tz).astimezone(timezone.utc)
    return x.minute, x.hour
dm, dh = u(d['digest']['hour'], d['digest']['minute'])
cl = str(d.get('sessions', {}).get('daily_clear', '04:00')).split(':')
cm, ch = u(cl[0], cl[1])
print(dm, dh, cm, ch)
" 2>/dev/null || echo '0 4 30 0')"
read -r DIG_MIN DIG_HOUR CLR_MIN CLR_HOUR <<<"$SCHED"

START="# >>> personal-os:${NAME} >>>"
END="# <<< personal-os:${NAME} <<<"
DIGEST_LINE="${DIG_MIN} ${DIG_HOUR} * * * flock -n ${HERE}/generated/digest.lock ${HERE}/scripts/run_digest.sh >> ${HERE}/generated/digest-cron.log 2>&1"
REMINDER_LINE="*/10 * * * * flock -n ${HERE}/generated/reminders.lock ${HERE}/scripts/run_reminders.sh >> ${HERE}/generated/reminders-cron.log 2>&1"
CLEAR_LINE="${CLR_MIN} ${CLR_HOUR} * * * flock -n ${HERE}/generated/clear.lock ${HERE}/scripts/run_clear.sh >> ${HERE}/generated/clear-cron.log 2>&1"

# Current crontab (tolerate 'no crontab for user').
EXISTING="$(crontab -l 2>/dev/null || true)"

# Strip any prior block for THIS instance, preserving everything else verbatim.
CLEANED="$(printf '%s\n' "$EXISTING" | awk -v s="$START" -v e="$END" '
  $0==s {skip=1; next}
  $0==e {skip=0; next}
  skip!=1 {print}
')"

if [ "$REMOVE" -eq 1 ]; then
  printf '%s\n' "$CLEANED" | sed '/^$/{:a;N;/\n$/ba};s/\n\{3,\}/\n\n/g' | crontab -
  echo "Removed cron block for instance '${NAME}'. Other cron lines preserved."
  exit 0
fi

mkdir -p "$HERE/generated"
NEW="$(printf '%s\n%s\n%s\n%s\n%s\n%s\n' "$CLEANED" "$START" "$DIGEST_LINE" "$REMINDER_LINE" "$CLEAR_LINE" "$END")"
printf '%s\n' "$NEW" | crontab -
echo "Installed cron for instance '${NAME}' (times converted from $(PYTHONPATH="$HERE" "$PY" -c 'from scripts import config; print(config.timezone())' 2>/dev/null||echo UTC) to UTC):"
echo "  digest      ${DIG_HOUR}:${DIG_MIN} UTC   reminders every 10 min   daily-clear ${CLR_HOUR}:${CLR_MIN} UTC"
echo "Verify with: crontab -l"
