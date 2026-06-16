#!/usr/bin/env bash
# =============================================================================
# personal-os — acceptance checks. Verify the system by OBSERVABLE BEHAVIOR.
#
#   ./check.sh                      # free: deterministic checks (no model calls)
#   PERSONAL_OS_LIVE_ENGINE=1 ./check.sh   # also exercise a real engine reply + digest
#
# Maps to the spec's acceptance criteria (a)-(g). Engine-touching checks (a, e1) are
# SKIPPED by default so the command is free; the honest-recall guarantee (d) and the
# storage/index/snapshot/gitignore/install checks run deterministically and can FAIL.
# =============================================================================
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

PASS=0; FAIL=0; SKIP=0
pass(){ printf '  \033[32m✅ PASS\033[0m  %s\n' "$1"; PASS=$((PASS+1)); }
fail(){ printf '  \033[31m❌ FAIL\033[0m  %s\n' "$1"; FAIL=$((FAIL+1)); }
skip(){ printf '  \033[33m⏭  SKIP\033[0m  %s\n' "$1"; SKIP=$((SKIP+1)); }
info(){ printf '  \033[36mℹ \033[0m %s\n' "$1"; }

# --- (f) engine separated from data: gitignore + nothing private tracked -----
echo "[f] engine separated from data (gitignore + committed tree)"
fok=1
for p in config/secrets.env config/config.yml authored/about-me.md generated; do
  git check-ignore -q "$p" 2>/dev/null || { fail "f: '$p' is NOT gitignored"; fok=0; }
done
bad="$(git ls-files | grep -E '^(config/config\.yml|config/secrets\.env|authored/[a-z-]+\.md$|generated/|conversations/)' || true)"
[ -z "$bad" ] || { fail "f: private files are tracked: $bad"; fok=0; }
if git ls-files -z | xargs -0 grep -lE '[0-9]{8,10}:[A-Za-z0-9_-]{35}' 2>/dev/null | grep -q .; then
  fail "f: a bot-token-like string appears in a tracked file"; fok=0
fi
[ "$fok" = 1 ] && pass "f: secrets & personal data gitignored; only engine+templates committed"

# --- (g) install.sh builds a working empty 2nd instance (sandbox) ------------
echo "[g] install.sh produces a working empty second instance"
SANDBOX="$(mktemp -d)"
trap 'rm -rf "$SANDBOX"' EXIT
if git archive HEAD | tar -x -C "$SANDBOX" 2>/dev/null; then
  if ( cd "$SANDBOX" && POS_INSTANCE_NAME=checktest POS_DATA_DIR=. \
        bash install.sh --non-interactive --skip-cron ) >"$SANDBOX/install.log" 2>&1; then
    pass "g: install.sh completed in a clean directory"
  else
    fail "g: install.sh failed — tail of log:"; tail -8 "$SANDBOX/install.log" | sed 's/^/        /'
  fi
else
  fail "g: could not export committed tree (is HEAD committed?)"
fi
SPY="$SANDBOX/venv/bin/python"
[ -x "$SPY" ] && pass "g: isolated venv created" || fail "g: no venv in sandbox"
[ -f "$SANDBOX/config/config.yml" ] && pass "g: config.yml generated from template" || fail "g: no config.yml"
[ -f "$SANDBOX/authored/about-me.md" ] && pass "g: authored files seeded from templates" || fail "g: authored files not seeded"

run_sandbox(){ ( cd "$SANDBOX" && PYTHONPATH=. "$SPY" - ); }

# --- (d) sourced recall + honest gap (engine-free, deterministic) ------------
echo "[d] recall returns the right answer WITH a source; admits gaps honestly"
if [ -x "$SPY" ]; then
  if run_sandbox <<'PY'
from scripts import index, recall
index.reindex_all(reset=True)
index.index_units("authored/about-me.md", "authored",
    [("authored/about-me.md", "My current project is called Volkeeper, a volatility trading bot.")])
r1 = recall.recall("what is my current project")
assert r1["found"], "a mentioned fact was NOT found"
assert any("about-me" in c["source_id"] for c in r1["citations"]), "no citation/source returned"
r2 = recall.recall("glorptak zzqwx an utterly unmentioned topic")
assert not r2["found"], "an unmentioned query should be NOT FOUND (honest gap)"
print("OK")
PY
  then pass "d: mentioned fact recalled with a source; unmentioned -> honest 'not found'"
  else fail "d: recall/honesty behavior is wrong"; fi
else skip "d: no sandbox venv"; fi

# --- (b) daily log exists + index grows (engine-free) ------------------------
echo "[b] a dated daily log exists with entries and the index grows"
if [ -x "$SPY" ]; then
  if run_sandbox <<'PY'
from scripts import index, paths
before = index.stats().get("chunks", 0)
p = paths.daily_file("2099-01-01"); p.parent.mkdir(parents=True, exist_ok=True)
p.write_text("---\ngenerated_at: 2099-01-01T00:00:00+00:00\nkind: daily-log\n---\n# Daily log\n\n"
             "<!-- turn source_id=daily/2099-01-01#001 turn_key=t ts=x source=test -->\n"
             "The user confirmed the deployment plan.\n", encoding="utf-8")
index.index_file(p, index.DAILY)
after = index.stats().get("chunks", 0)
assert after > before, f"index did not grow ({before}->{after})"
assert p.read_text().count("<!-- turn ") >= 1, "daily log has no entry marker"
print("OK", before, "->", after)
PY
  then pass "b: daily log entry written and index grew (chunks increased)"
  else fail "b: storage/index growth failed"; fi
else skip "b: no sandbox venv"; fi

# --- (c) capped, sourced injection snapshot ----------------------------------
echo "[c] injection snapshot exists, is capped, reflects identity"
if [ -x "$SPY" ]; then
  if run_sandbox <<'PY'
from scripts import snapshot
s = snapshot.build_snapshot()
assert s["sources"], "snapshot lists no identity sources"
assert (s["token_estimate"] <= s["token_cap"]) or s["over_cap"], "snapshot neither under cap nor flagged over-cap"
assert "Identity" in s["body"], "snapshot missing identity section"
print("OK tokens", s["token_estimate"], "/", s["token_cap"])
PY
  then pass "c: snapshot exists, capped (or honestly flagged), reflects identity"
  else fail "c: snapshot check failed"; fi
else skip "c: no sandbox venv"; fi

# --- (a) sensible engine reply (LIVE — opt-in, costs API) --------------------
echo "[a] you can send a message and get a sensible reply"
if [ "${PERSONAL_OS_LIVE_ENGINE:-0}" = "1" ] && [ -x "$SPY" ]; then
  if run_sandbox <<'PY'
from scripts import assistant
r = assistant.respond("In one short sentence, confirm you are working.")
assert not r["engine_error"], "engine error"
assert len(r["answer"].strip()) > 0, "empty answer"
print("OK:", r["answer"][:80])
PY
  then pass "a: engine returned a sensible reply"
  else fail "a: engine reply failed"; fi
else skip "a: set PERSONAL_OS_LIVE_ENGINE=1 to test a live reply (uses the model; costs API)"; fi

# --- (e) daily digest machinery + delivery -----------------------------------
echo "[e] a digest is generated on schedule and arrives on Telegram"
if [ "${PERSONAL_OS_LIVE_ENGINE:-0}" = "1" ] && [ -x "$SPY" ]; then
  if ( cd "$SANDBOX" && PYTHONPATH=. "$SPY" -m scripts.digest --date 2099-01-02 --no-push ) >/dev/null 2>&1 \
     && [ -f "$SANDBOX/generated/digests/2099-01-02.md" ]; then
    pass "e1: digest file generated with content"
  else fail "e1: digest generation failed"; fi
else skip "e1: set PERSONAL_OS_LIVE_ENGINE=1 to generate a digest (uses the model)"; fi
if crontab -l 2>/dev/null | grep -q '>>> personal-os'; then
  info "e2: daily-digest cron is registered (it runs unattended)"
else
  info "e2: cron not registered yet — run ./install.sh or scripts/install_cron.sh"
fi
info "e2: real Telegram delivery is confirmed by messaging your bot once (cannot be asserted offline)"

# --- safety: unrelated cron lines preserved ----------------------------------
echo "[safety] unrelated crontab entries are preserved"
if crontab -l 2>/dev/null | grep -q 'n8n-tether-watchdog'; then
  info "the pre-existing n8n-tether-watchdog cron line is still present"
else
  info "(no n8n-tether-watchdog cron line found — fine if you never had one)"
fi

# --- summary -----------------------------------------------------------------
echo
echo "================ $PASS passed · $FAIL failed · $SKIP skipped ================"
if [ "$FAIL" -eq 0 ]; then
  echo "ACCEPTANCE: OK ✅  (skips are engine/Telegram checks you can run live)"
  exit 0
else
  echo "ACCEPTANCE: $FAIL FAILURE(S) ❌"
  exit 1
fi
