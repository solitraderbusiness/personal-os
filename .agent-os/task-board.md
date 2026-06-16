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

## Phase 4 — Telegram front-door
- [ ] scripts/telegram_bot.py (long-poll, single chat_id auth, token redaction, push)
- [ ] Live test once token is in secrets.env

## Phase 5 — Proactive digest
- [ ] scripts/digest.py (priorities + logs + feedback → digest → Telegram push)
- [ ] scripts/run_digest.sh (cron wrapper)
- [ ] scripts/install_cron.sh (marker-block crontab; preserve n8n line)

## Phase 6 — Replicability + docs + tests
- [ ] install.sh (idempotent fresh isolated instance)
- [ ] AGENT.md (portable operating contract; the 7 principles)
- [ ] check.sh (engine-free criterion-d layer; engine checks opt-in; criteria a–g)
- [ ] tests/ (offline unit tests: engine, capture, index, snapshot)
- [ ] README.md (what / install / verify + acceptance checklist)
- [ ] Run install.sh in a clean dir → verify empty 2nd instance works
