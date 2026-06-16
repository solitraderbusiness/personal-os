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

# Read instance name + schedule from config (fall back to defaults).
NAME="$(PYTHONPATH="$HERE" "$PY" -c 'from scripts import config; print(config.instance_name())' 2>/dev/null || echo personal-os)"
read -r HOUR MIN <<EOF
$(PYTHONPATH="$HERE" "$PY" -c 'from scripts import config; d=config.load_config()["digest"]; print(d.get("hour",7), d.get("minute",30))' 2>/dev/null || echo "7 30")
EOF

START="# >>> personal-os:${NAME} >>>"
END="# <<< personal-os:${NAME} <<<"
LOCK="$HERE/generated/digest.lock"
LOG="$HERE/generated/digest-cron.log"
CRON_LINE="${MIN} ${HOUR} * * * flock -n ${LOCK} ${HERE}/scripts/run_digest.sh >> ${LOG} 2>&1"

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
NEW="$(printf '%s\n%s\n%s\n%s\n' "$CLEANED" "$START" "$CRON_LINE" "$END")"
printf '%s\n' "$NEW" | crontab -
echo "Installed daily-digest cron for instance '${NAME}' at ${MIN} ${HOUR} (server time)."
echo "Verify with: crontab -l"
