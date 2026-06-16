# personal-os — Task Board

`[ ]` todo · `[~]` in progress · `[x]` done. Grouped by phase.

## Phase 0 — Harden server
- [x] Verify ufw active + SSH/22 allowed
- [x] Verify SSH key auth present
- [~] Disable password login (deferred to explicit go-live confirm; one-liner ready)

## Phase 1 — Foundation  ✅
- [x] git init (branch main) + local identity
- [x] .gitignore (verified airtight via git check-ignore)
- [x] Build brain (.agent-os/*)
- [x] Folder structure
- [x] authored/*.template.md (7 templates)
- [x] config/config.example.yml + secrets.env.example
- [x] skills/ stub + requirements.txt
- [x] Phase 1 commit

## Phase 2 — Memory engine  ✅
- [x] scripts/config.py (+ secrets loader, surgical set_runtime)
- [x] scripts/paths.py (single source of all paths)
- [x] scripts/engine.py (model-agnostic; JSON-field errors; injection guard; engine.log)
- [x] scripts/embeddings.py (model2vec + hashing fallback)
- [x] scripts/index.py (sqlite-vec + FTS5; RRF; FTS5-only degradation; write-lock; seam)
- [x] scripts/capture.py (turn → Haiku → flock'd daily log → index)
- [x] scripts/snapshot.py (capped, cached, timestamped projection)
- [x] scripts/recall.py (multi-tier; sourced; honest gaps)
- [x] Phase 2 verified (spine tests + error-path + comment-preservation)

## Phase 3 — Runtime loop (terminal)  ✅
- [x] scripts/assistant.py (shared respond() loop)
- [x] scripts/chat.py (REPL; /recall /snapshot /reindex /stats /feedback)
- [x] scripts/feedback.py
- [x] End-to-end verified (recall-with-source + honest gap, live engine)

## Phase 4 — Telegram front-door  ✅
- [x] scripts/telegram_bot.py (long-poll, single chat_id auth, token redaction, push)
- [~] Live test once token is in secrets.env (token not yet provided)

## Phase 5 — Proactive digest  ✅
- [x] scripts/digest.py (priorities + logs + feedback → digest → Telegram push)
- [x] scripts/run_digest.sh (cron wrapper; verified in bare env)
- [x] scripts/install_cron.sh (marker-block crontab; n8n line verified preserved; idempotent)
- [x] Daily digest cron registered for this instance (30 7 server time)

## Phase 6 — Replicability + docs + tests  ✅
- [x] install.sh (idempotent fresh isolated instance)
- [x] AGENT.md (portable operating contract; the 7 principles)
- [x] check.sh (engine-free criterion-d layer via hashing; engine checks opt-in; criteria a–g)
- [x] tests/test_offline.py (8 offline unit tests, all pass)
- [x] README.md (what / install / verify + acceptance checklist + cost/privacy/replicate)
- [x] install.sh in a clean dir → empty 2nd instance verified (check.sh criterion g)
- [x] ./check.sh => 10 passed · 0 failed (live engine) / 8 passed · 0 failed (free)

## Go-live (needs user)
- [x] Telegram token in secrets.env → live bot test (works; @Jarvis_Summit_bot)
- [ ] Fill authored/about-me.md from draft → reindex
- [x] git push (token from store; pushed to origin/main)
- [~] Disable SSH password login (optional; user confirm)

## Phase 7 — Active memory (auto-learn + reminders)  ✅ DONE
Decision: "auto-learn now, confirm later" two-tier (Tier 1 auto -> generated learned
store, used instantly; Tier 2 authored canon updated only on approval). TZ Asia/Tehran.
- [x] config.instance.timezone + config/example
- [x] scripts/extract.py (one cheap call -> summary + preferences/ideas/rules/reminders)
- [x] scripts/learned.py (machine-owned learned store; dedup; render; promote/drop)
- [x] scripts/reminders.py (tz-aware add/due/check+push; idempotent notify)
- [x] integrate into capture (analyze_turn) + snapshot (learned + upcoming) + digest (pending+upcoming)
- [x] telegram /keep /drop /learned /reminders
- [x] reminders tick cron (every 10 min) + run_reminders.sh; install_cron updates (n8n preserved)
- [x] verified end-to-end (extract+tz conversion+promote+drop+reminders)
- [x] GUARD added after D19 incident: POS_DATA_DIR test isolation + raw-transcript backup
- [ ] (carryover) check.sh additions for active memory; review workflow

## Phase 8 — Sessions & topics (user request 2026-06-16)  ⬜ NEXT
- Telegram forum TOPICS: each topic = its own session/thread; route via message_thread_id;
  reply in-topic; tag memory by topic so each thread is separately recallable. Bot stays
  locked to the one authorized group (topics are sub-threads).
- Per-session short-term CONTEXT BUFFER (capped) for conversational continuity within a
  topic (the system is currently stateless per-turn — no growing context). This buffer is
  what "clear" clears.
- /clear (clears current topic's buffer) + DAILY auto-clear at 04:00 Asia/Tehran (cron).
- INVARIANT: every turn is written to long-term memory BEFORE any clear, so clearing only
  drops short-term context — topics can always be recalled/resumed later. (Already true:
  capture writes per-turn.)
