# personal-os — Current State

_Updated: 2026-06-16. Keep accurate so the build can resume at any point._

## Phase status
- **Phase 0 — Harden server:** ✅ verified / 🟡 one deferred item.
  ufw active + SSH/22 allowed; 5 keys present; pubkey auth on. Password-login
  disable deferred to explicit go-live confirm (see decision D9). No lockout risk now.
- **Phase 1 — Repo + .gitignore + structure + templates + build brain:** ✅ done.
  git init (main), verified-airtight .gitignore, build brain, 7 authored templates,
  config.example.yml + secrets.env.example, requirements.txt, skills/ stub.
- **Phase 2 — Three-jobs memory engine:** ✅ done + verified. config/paths/secrets via
  config.py+paths.py; model-agnostic engine.py (sandboxed claude -p, JSON-field error
  detection, injection guard, engine.log); embeddings.py (model2vec+hashing fallback);
  index.py (sqlite-vec + FTS5 hybrid + RRF, FTS5-only degradation, write-lock); capture.py
  (Haiku summary → flock'd daily log → index); snapshot.py (capped cached projection);
  recall.py (sourced, honest gaps). All design-review blockers folded in (D17a–k).
- **Phase 3 — Runtime loop (terminal):** ✅ done + verified end-to-end. assistant.py
  (the one shared respond() loop) + chat.py REPL. Live test: established a fact, recalled
  it WITH a source [daily/...#001], and honestly said "I don't have that" for an
  unmentioned fact. Index grew, daily log written, snapshot capped.
- **Phase 4 — Telegram front-door:** ✅ code done + verified (graceful no-token; token
  redaction; single-owner enforcement; long-line splitting). Live test pending the
  user's token in secrets.env.
- **Phase 5 — Proactive digest + cron:** ✅ done + verified. digest.py (reads
  priorities/reminders/recent logs/feedback → cheap-tier brief → timestamped file →
  Telegram push when configured; observable on engine failure). run_digest.sh +
  install_cron.sh registered the daily job; VERIFIED the unrelated n8n cron line
  survives, registration is idempotent, and the wrapper runs in a bare `env -i`
  environment (engine_ok true). feedback.py loop done.
- **Phase 6 — install.sh + AGENT.md + check.sh + tests + README:** 🔵 next.

## In flight
- Design-validation workflow (wf_23cfcd63-754) COMPLETE; ADRs + 3 adversarial critiques
  folded into decision log (D17) and code. No personal-data-in-git leak found by critics.

## Known external dependencies (provided by user at setup, not committed)
- Telegram bot token → `config/secrets.env` (user pastes; "now").
- Git push: fine-grained PAT (Contents: read/write) via credential store, or deploy key.
- Draft `about-me.md` content → user fills `authored/about-me.md` after templates exist.

## How to resume
Read this file + `decision-log.md` + `task-board.md`, then continue at the first
non-done phase. The engine code lives in `scripts/`; run `./check.sh` to see status.
