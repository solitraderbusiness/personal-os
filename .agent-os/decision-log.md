# personal-os — Decision Log

Every non-obvious choice and why. Newest at the bottom. Dates absolute.

## 2026-06-16 — Environment & stack (verified on target server srv921235)
- **D1 — Language: Python 3.12.** Mature libs for embeddings (model2vec), sqlite-vec
  bindings, and a stdlib-only Telegram long-poll. Single language across the engine.
- **D2 — Engine boundary: the local `claude` CLI in print mode.** `claude -p
  --model <model> --output-format json` returns JSON with a `.result` field and
  works headlessly using existing Claude Code auth — **no API key needed**. Verified
  live (`ENGINE_OK`). One adapter module (`scripts/engine.py`) wraps it; swapping to
  a direct API or local model = replace only that module. This is the model-agnostic
  seam (principle 3) and the cron-friendly headless path the spec asks for.
- **D3 — Model tiers.** Answer tier = Claude Code default model; summary/digest cheap
  tier = `claude-haiku-4-5-20251001`. Both via the same adapter with `--model`. Tiers
  are config keys so they are swappable.
- **D4 — Embeddings: model2vec (static embeddings) + deterministic hashing fallback.**
  No torch, CPU-only, zero API cost, fast. Behind a pluggable embedder interface; if
  the model isn't downloaded, a deterministic hashing embedder keeps the system
  working offline and lets tests run without network. (model2vec 0.8.2 confirmed
  pip-available.)
- **D5 — Vector store: sqlite-vec (vec0) + FTS5 in ONE sqlite file.** Hybrid search
  fuses semantic + keyword via Reciprocal Rank Fusion (RRF). Single portable file
  (principle 3). Reranker is a clearly-marked no-op seam with a TODO (out of scope v1).
  (sqlite-vec 0.1.9 confirmed pip-available.)
- **D6 — Telegram: lightweight long-poll using stdlib + `requests`.** getUpdates /
  sendMessage; restricted to a single authorized chat_id (captured on first message).
  No heavy framework (understood > opaque). Token from gitignored `secrets.env`.
- **D7 — Scheduling: cron** (spec default), invoking the digest headlessly via the
  venv + `claude -p`.

## 2026-06-16 — Deployment choices (from user Q&A)
- **D8 — Run as root in `/root/projects/personal-os` for now** (user choice). Non-root
  service user remains the documented go-live recommendation, and `install.sh` runs
  as whatever user invokes it, so fresh instances are non-root by default.
- **D9 — Phase 0 hardening status.** ufw is **active** and **allows SSH/22** (verified)
  → no firewall lockout risk. 5 SSH keys present in root's authorized_keys; pubkey
  auth on. `PasswordAuthentication` is currently effectively **yes** (cloud-init file
  overrides the cloudimg one). Disabling password login is *safe* given the keys, but
  is deferred to an explicit go-live confirmation rather than silently changing how
  the user logs in (principle 7). Documented as a one-liner toggle.
- **D10 — Telegram token: user provides "now"** into gitignored `config/secrets.env`
  themselves (they paste it via the shell, never to me, never committed). They are
  regenerating the token before any public exposure.

## 2026-06-16 — Build method
- **D11 — `.agent-os/` is committed** (build documentation, contains no personal data).
  `.claude/` is gitignored (harness state / possible transcripts).
- **D12 — Architecture validated by a design workflow** (6 subsystem architects → 1
  synthesizer producing frozen interfaces/ADRs → 3 adversarial critics). Findings are
  folded into this log and the implementation before coding the engine.
- **D13 — Engine subprocess is SANDBOXED.** Verified invocation:
  `claude -p --model <m> --system-prompt-file <f> --allowedTools "" --max-turns 1
  --output-format json`, user content via **stdin**. Empty allowed-tools + single
  turn = a pure text completion with NO filesystem/bash access, so memory content
  passed as data can never trick the engine into running tools (injection defense,
  principles 6/7). System prompt via temp file + stdin user = no argv length limits.
- **D14 — Embedding dimension = 256** (model2vec `minishlab/potion-base-8M`, verified
  download+embed → shape (n,256) float32). The index probes the real dim at creation
  and stores it in a meta table, so a model swap is detected (rebuild required) rather
  than silently corrupting vectors. Vectors are L2-normalized → L2 distance ranks like
  cosine; a cosine-ish similarity is derived for the recall confidence signal.
- **D15 — Package layout.** Library lives in the `scripts/` Python package; entrypoints
  run as `venv/bin/python -m scripts.<chat|telegram_bot|digest>` from the repo root.
  `config.py` locates `config/config.yml` relative to its own file (no dependency on
  `paths.py`); `paths.py` derives all data paths from `config.paths.data_dir` (default =
  repo root) so a fresh instance can point at its own data dir (install.sh).
- **D16 — Honest epistemics is prompt+retrieval driven, not a brittle threshold.** The
  assistant answers personal-history questions ONLY from retrieved MEMORY (passed as
  delimited DATA); if memory lacks it, it says "I don't have that" and never invents.
  Retrieval also returns a confidence signal; very weak retrieval is flagged to the
  model as "no strong matches".

## 2026-06-16 — Design-workflow review folded in (run wf_23cfcd63-754, 10 agents)
The synthesizer's ADRs confirmed the spine design; 3 adversarial critics found real
issues in the already-written spine. Resolutions (D17):
- **D17a — engine error detection (BLOCKER, 3× flagged).** Rewrote engine.py to be
  JSON-field-first: success requires valid JSON AND `is_error` falsey AND
  `api_error_status` null AND non-empty `.result`; never gate on returncode. Error
  KINDS {api_error,timeout,not_found,bad_output,empty}; retry only timeout / 5xx,
  never 4xx; missing binary -> not_found. Guards principle 6 (an error apology must
  never surface as a real answer).
- **D17b — INJECTION_GUARD + closing-tag sanitization (major).** engine prepends a
  standing INJECTION_GUARD system instruction; data_block neutralizes any literal
  closing delimiter so poisoned memory can't break out of the DATA fence on later
  recall. Empty-allowedTools sandbox is the structural backstop.
- **D17c — engine.log (major).** engine appends ONE JSON line/call (ts,model,tier,
  duration_ms,ok,cost) to generated/memory/index/engine.log — metadata only, never
  payloads. Gives per-turn cost/observability.
- **D17d — config.set_runtime surgical (BLOCKER, 2× flagged).** Replaced the full
  yaml-dump rewrite (which destroyed the human's comments — violates principle 1)
  with a textual rewrite of ONLY a machine-managed `runtime:` block. chat_id now lives
  at runtime.telegram_chat_id.
- **D17e — index FTS5-only degradation (BLOCKER, 2× flagged).** sqlite-vec import/load
  is guarded; on failure or embedder name/dim mismatch the index degrades to
  keyword-only search and never raises inside search/recall/capture. Backend NAME +
  dim both stored in meta and compared (a same-dim model swap is detected, not silently
  mixed). A 'rebuild required' signal is surfaced, not a crash.
- **D17f — index write lock + safe reset (major).** index writes take a process-level
  flock (index.db.lock); busy_timeout raised to 30s; reindex --reset rebuilds into a
  temp db then os.replace (never unlinks a live db).
- **D17g — frozen daily-log format.** Each turn entry begins with an HTML-comment
  marker `<!-- turn source_id=daily/YYYY-MM-DD#NNN turn_key=<sha> ts=<iso> -->`
  followed by markdown. capture WRITES it; index._units_daily and snapshot.recent
  READ it (split on the marker, reuse source_id verbatim). Cross-module contract.
- **D17h — cost-aware, free-by-default check.sh.** Engine-touching checks (criterion
  a, e1 digest) run only with PERSONAL_OS_LIVE_ENGINE=1 (default SKIP). Measured cost
  is ~$0.17/answer turn because empty models.answer => CLI default = opus-4-8[1m]
  (~15k cache tokens/call). README documents this + how to pin a cheaper answer model,
  and that swapping engine.py to the direct API removes the Claude Code overhead.
- **D17i — crontab safety.** install_cron.sh edits via `crontab -l` -> splice a tagged
  `# >>> personal-os:<name> >>>` block -> `crontab -` (never `crontab <file>`); the
  cron command is flock-wrapped. The existing `n8n-tether-watchdog.sh` line MUST and
  WILL survive; check.sh asserts it.
- **D17j — naming 'drift' deliberately NOT chased.** Since I author every module, I keep
  my consistent config keys (embedding:, recall.weak_sim/candidate_k, snapshot.ttl_minutes,
  memory.db) rather than the synthesizer's alternates. No functional difference; avoids churn.
- **D17k — FTS5 kept standalone (not external-content).** A standalone fts5(text) table
  with managed rowid is simpler/more robust than external-content + triggers. The FTS
  table is a derived search index over the chunks source-of-truth, not a duplicated
  fact — consistent with principle 2 (understood > opaque).

## 2026-06-16 — Phase 7 (active memory) + a real mistake to never repeat
- **D18 — Active memory built.** Auto-extraction (one Haiku call -> summary + preferences/
  ideas/rules/timed-reminders) to a machine-owned Tier-1 store (learned.json), used
  instantly in the snapshot; promotion to authored canon is approval-gated (/keep, /drop).
  Timezone-aware reminders (Asia/Tehran) with a 10-min cron tick pushing Telegram nudges
  before due. /keep /drop /learned /reminders bot commands; digest lists pending + upcoming.
## 2026-06-16 — Natural companion UX + speed + resilience (user feedback)
- **D20a — Conversational, no internals leaked.** The honest-epistemics design was leaking
  file paths/source tags ([authored/about-me.md], [daily/...]) and meta-talk into replies.
  Fixed: STANDING_RULES rewritten to "talk like a friend, never mention files/paths/sources";
  AGENT.md is NO LONGER injected into answers (it's full of architecture/file talk — kept as
  repo doc only); recall memory block, snapshot sections, recent-memory + reminder lines all
  stripped of source ids/paths; the appended "— sources:" line removed. Verified: a real
  reply about the user contained ZERO leak patterns. Honesty (no fabrication, admit gaps)
  preserved via the prompt; provenance stays internal (recall still has source_ids for the
  system + check.sh). This adjusts principle 6's *presentation* per the user: honest, not
  technical.
- **D20b — Model router (user's design).** assistant.route_tier() picks by message
  complexity, instantly (no extra call): default Haiku (answer), Sonnet (deep) on
  reasoning keywords / long messages, Opus (code) on coding keywords. Faster + cheaper for
  casual chat; escalates only when needed.
- **D20c — Speed.** Capture already async (D-perf). Trimmed per-call context: recall k 6->4,
  sessions max_turns 10->6, and dropped the full AGENT.md from the prompt. ~7s Haiku floor
  remains (Claude Code CLI overhead) — documented; direct-API would be faster but the user
  wants the Max subscription.
- **D20d — OpenRouter fallback.** engine.complete() falls back to OpenRouter
  (google/gemini-2.5-flash) when the Claude CLI call fails (overload/down), keeping the same
  injection-guarded system + untrusted-data payload. Claude stays primary (subscription);
  fallback only on failure. Verified working. (Telegram bot live-reloads config each poll, so
  model/key/owner changes need no restart.)

- **D19 — LESSON (mistake I made, must never repeat): I deleted live user data during a
  test.** A throwaway test's cleanup ran `paths.daily_file().unlink()` + `index.reindex_all(
  reset=True)` against the LIVE instance while the user was actively chatting with the bot —
  destroying ~53 real captured turns from that day (unrecoverable locally; raw transcripts
  were off; no /proc handle). ROOT CAUSE: ran a destructive test against live data instead
  of an isolated dir. GUARDS ADDED: (1) `POS_DATA_DIR` env override in paths.data_root() so
  any test/sandbox runs fully isolated — ALWAYS set it for tests, NEVER unlink live paths;
  (2) enabled `capture.store_raw_transcript` so raw turn text is backed up in conversations/
  and a lost summary/index never means lost content. RULE: never run a cleanup that deletes
  daily logs / resets the index against a live data_dir; tests use POS_DATA_DIR=$(mktemp -d).
