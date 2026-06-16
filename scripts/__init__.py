"""personal-os engine package.

A self-hosted personal AI memory OS. Modules:
  config      — load config.yml + secrets.env (no personal data here)
  paths       — single source of truth for every filesystem path
  engine      — model-agnostic adapter (THE swappable boundary); sandboxed `claude -p`
  embeddings  — local static embeddings (model2vec) + deterministic hashing fallback
  index       — sqlite-vec + FTS5 hybrid store (chunks, upsert, RRF search, rerank seam)
  capture     — turn -> Haiku summary -> daily log -> index
  snapshot    — capped, cached, timestamped identity+recent-memory projection
  recall      — multi-tier (snapshot -> hybrid index) sourced recall that admits gaps
  assistant   — the shared per-message runtime loop (used by every front-end)
  chat        — terminal REPL front-end
  telegram_bot— Telegram long-poll front-end (single authorized chat)
  digest      — proactive daily digest (cron) + feedback loop

Run entrypoints from the repo root, e.g.:
  venv/bin/python -m scripts.chat
"""
