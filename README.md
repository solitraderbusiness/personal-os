# personal-os

A **self-hosted personal AI assistant with a real memory**. It runs on your own
server, you talk to it from one place (Telegram, or the terminal), it learns you over
time, and it proactively surfaces what matters in a daily digest. Your data stays on
your machine; only the model call leaves. A fresh, isolated copy installs for someone
else with one command — without any of your personal data coming along.

You don't need to read the code to trust it: **`./check.sh` verifies the system by
observable behavior.**

---

## What makes it different

- **Authored vs generated.** Files in `authored/` are *yours* — durable, human-owned,
  never silently rewritten. Files in `generated/` are machine-owned, regenerable, and
  timestamped. The folder a file lives in tells you who owns it.
- **One source of truth.** Every fact lives in exactly one file; everything else refers
  to it. Update one file and it propagates.
- **Honest memory.** When it recalls something, it tells you **where it came from**
  (`[daily/2026-06-16#002]`, `[authored/about-me.md]`). When it doesn't know, it says
  **"I don't have that"** — it never invents your own history back at you.
- **Model-agnostic.** Your durable data is plain Markdown + a local vector index. The
  AI engine is a *replaceable part* behind one small adapter (`scripts/engine.py`).
- **Local-first & private.** Authored files, memory, logs, and the vector index all live
  on your server. Secrets live in a gitignored file, never in code.

---

## The three jobs of memory

1. **Storage** — after every turn, a cheap fast model (Haiku) condenses it and appends a
   timestamped line to a dated **daily log**. Nothing is left to chance about what's
   "worth keeping" — everything is captured, condensed.
2. **Injection** — at the start of a session a capped (~1,800-token) **snapshot** of your
   identity + recent memory is built once and reused, so those tokens are paid once.
3. **Recall** — everything is indexed as **local vectors** (zero API cost). Search is
   hybrid (semantic + keyword), and answers come back **with citations**, or with an
   honest "I don't have that."

---

## Install (one command)

Requires Ubuntu (or similar) with Python 3, and the `claude` CLI already authenticated
(this is the default engine — no API key needed).

```bash
./install.sh
```

It creates a venv, installs dependencies, generates `config/config.yml` and
`config/secrets.env` from templates (prompting for an instance name and, optionally,
your Telegram bot token), copies the authored templates into editable files, builds the
local index, and registers the daily-digest cron job. It is **idempotent** — re-running
never overwrites your filled config, secrets, authored files, or memory.

Then:

1. **Fill in your authored files** (in `authored/`, start with `about-me.md`), then
   `venv/bin/python -m scripts.index reindex`.
2. **Add your Telegram bot token** (from [@BotFather](https://t.me/BotFather)) to
   `config/secrets.env` if you didn't during install.

---

## Talk to it

- **Terminal:** `venv/bin/python -m scripts.chat`
  (slash commands: `/recall`, `/snapshot`, `/reindex`, `/stats`, `/feedback`, `/help`)
- **Telegram:** `venv/bin/python -m scripts.telegram_bot` (run it under `tmux`), then
  **message your bot once** — the first chat to message it becomes the sole authorized
  chat. Everyone else is ignored.
- **Daily digest:** generated automatically by cron and pushed to Telegram. Reply with
  `/feedback useful <item>` or `/feedback noise <item>` to tune what it surfaces.

---

## Verify it works — `./check.sh`

```bash
./check.sh                          # free: deterministic checks, no model calls
PERSONAL_OS_LIVE_ENGINE=1 ./check.sh   # also exercise a live reply + digest (uses the model)
```

The acceptance checklist it covers:

| | Criterion | How it's checked |
|---|---|---|
| a | Send a message → sensible reply | live (opt-in) |
| b | A dated daily log appears; the index grows | deterministic |
| c | The injection snapshot exists, is capped, reflects identity | deterministic |
| d | Mentioned things recall **with a source**; unmentioned → honest "I don't have that" | deterministic |
| e | A digest is generated on schedule and arrives on Telegram | digest live (opt-in); delivery confirmed by messaging the bot |
| f | Your filled files & all `generated/` are gitignored; repo holds only engine + empty templates | deterministic |
| g | `install.sh` in a clean dir produces a working empty 2nd instance | deterministic (sandbox install) |

`./check.sh` is **free by default** — it never calls the model unless you opt in. Offline
unit tests: `PYTHONPATH=. venv/bin/python tests/test_offline.py`.

---

## Cost note (important)

The engine is the local `claude` CLI. With `models.answer` left blank, answers use the
CLI's **default model** (here, Opus) — roughly **$0.15–0.20 per answer turn** including
Claude Code's prompt overhead. Per-turn capture adds a small Haiku call. To control cost:

- Pin a cheaper answer model in `config/config.yml` (`models.answer: "claude-sonnet-4-6"`),
  or
- Swap the engine to the direct Anthropic API by editing **only** `scripts/engine.py`
  (the model-agnostic seam) — this removes the Claude Code prompt overhead.

The daily digest uses the cheap (Haiku) tier.

---

## Privacy & security

- Secrets (Telegram token, etc.) live only in gitignored `config/secrets.env`, never in
  code, never logged. **This repo is public — never commit a secret.**
- The engine runs **sandboxed** (no tools, single turn): stored memory and messages are
  passed as *data*, never as instructions, so nothing in your notes can make the engine
  take an action.
- The assistant **proposes** changes to your authored files; it never rewrites them on
  its own.

---

## Replicate for someone else

```bash
git clone https://github.com/solitraderbusiness/personal-os.git
cd personal-os && ./install.sh
```

They fill their own authored files and add their own bot token. Each instance is fully
separate — its own data, its own bot, its own memory. No shared store. Your data is never
part of what they install.

---

## Operations

- **Re-index** after editing authored files: `venv/bin/python -m scripts.index reindex`
  (`--reset` after changing the embedding model).
- **Cron** is registered per instance via a tagged block; `scripts/install_cron.sh
  --remove` removes only this instance's job, preserving any other cron lines.
- **Headless auth:** the cron digest relies on the `claude` CLI's existing login. If it
  expires, re-authenticate the CLI; failures are logged to `generated/digest-cron.log`
  and noted in the digest file itself.
- **Build notes & decisions** live in `.agent-os/` (constitution, decision log, current
  state, task board).
