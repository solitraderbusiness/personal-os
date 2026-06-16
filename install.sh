#!/usr/bin/env bash
# =============================================================================
# personal-os — one-command setup for a FRESH, ISOLATED instance.
#
# Idempotent and data-preserving: it never overwrites a filled config, secrets,
# authored file, or existing memory. Run it again any time to repair an instance.
#
#   ./install.sh                 # interactive
#   ./install.sh --non-interactive [--skip-cron]
# Env overrides (used by --non-interactive and by check.sh's sandbox):
#   POS_INSTANCE_NAME, POS_DATA_DIR, POS_TELEGRAM_TOKEN
# =============================================================================
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

NONINTERACTIVE=0
SKIP_CRON=0
for a in "$@"; do
  case "$a" in
    --non-interactive) NONINTERACTIVE=1 ;;
    --skip-cron) SKIP_CRON=1 ;;
    *) echo "unknown flag: $a" >&2; exit 2 ;;
  esac
done

say() { printf '\033[1m• %s\033[0m\n' "$*"; }

ask() {  # ask <prompt> <default> <varname>; honors env override and --non-interactive
  local prompt="$1" def="$2" __var="$3" envval="${!4:-}"
  if [ -n "$envval" ]; then printf -v "$__var" '%s' "$envval"; return; fi
  if [ "$NONINTERACTIVE" -eq 1 ]; then printf -v "$__var" '%s' "$def"; return; fi
  local ans; read -r -p "$prompt [$def]: " ans || true
  printf -v "$__var" '%s' "${ans:-$def}"
}

# --- 1. Python venv + dependencies ------------------------------------------
say "Setting up Python venv + dependencies"
[ -d venv ] || python3 -m venv venv
venv/bin/pip install -q --upgrade pip
venv/bin/pip install -q -r requirements.txt
PY="$HERE/venv/bin/python"

# --- 2. config.yml (copy from example only if absent) -----------------------
if [ ! -f config/config.yml ]; then
  say "Creating config/config.yml"
  cp config/config.example.yml config/config.yml
  ask "Instance name (one word)" "personal-os" INAME POS_INSTANCE_NAME
  ask "Data directory (where your private data lives; '.' = here)" "." DDIR POS_DATA_DIR
  sed -i "s#^  name: .*#  name: \"${INAME}\"#" config/config.yml
  sed -i "s#^  data_dir: .*#  data_dir: \"${DDIR}\"#" config/config.yml
else
  say "config/config.yml exists — leaving it untouched"
fi

# --- 3. secrets.env (copy from example only if absent) ----------------------
if [ ! -f config/secrets.env ]; then
  say "Creating config/secrets.env (gitignored, chmod 600)"
  cp config/secrets.env.example config/secrets.env
  chmod 600 config/secrets.env
  ask "Telegram bot token (optional — leave blank to add later)" "" TOKEN POS_TELEGRAM_TOKEN
  if [ -n "$TOKEN" ]; then
    sed -i "s#^TELEGRAM_BOT_TOKEN=.*#TELEGRAM_BOT_TOKEN=${TOKEN}#" config/secrets.env
  fi
else
  say "config/secrets.env exists — leaving it untouched"
fi

# --- 4. data tree + authored files (copy templates only if absent) ----------
say "Ensuring data directories"
"$PY" -c "from scripts import paths; paths.ensure_dirs()"
AUTHORED_DIR="$("$PY" -c 'from scripts import paths; print(paths.authored_dir())')"
for t in authored/*.template.md; do
  base="$(basename "$t" .template.md)"
  dst="${AUTHORED_DIR}/${base}.md"
  if [ ! -f "$dst" ]; then cp "$t" "$dst"; fi
done
say "Authored files are in: ${AUTHORED_DIR}  (fill them in to teach the assistant about you)"

# --- 5. initialize / build the local vector index ---------------------------
say "Building the local vector index"
"$PY" -m scripts.index reindex >/dev/null
"$PY" -m scripts.index stats | sed 's/^/    /'

# --- 6. register the daily-digest cron --------------------------------------
if [ "$SKIP_CRON" -eq 1 ]; then
  say "Skipping cron registration (--skip-cron)"
else
  say "Registering the daily-digest cron job"
  bash scripts/install_cron.sh || echo "  (cron registration skipped/failed — non-fatal)"
fi

cat <<EOF

✅ personal-os instance ready.

Next steps:
  1. Fill in your authored files in:  ${AUTHORED_DIR}
     (start with about-me.md). Then run:  $HERE/venv/bin/python -m scripts.index reindex
  2. Add your Telegram bot token to config/secrets.env (from @BotFather), if not done.
  3. Talk in the terminal:   $HERE/venv/bin/python -m scripts.chat
  4. Run the Telegram bot:    $HERE/venv/bin/python -m scripts.telegram_bot   (then message it once)
  5. Verify everything:       ./check.sh

EOF
