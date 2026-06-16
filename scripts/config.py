"""Load instance config (config.yml merged over defaults) and secrets (secrets.env).

No personal data lives here. config.yml + secrets.env are gitignored; only the
*.example files are committed. `config.py` finds these relative to its own location
so it has no dependency on paths.py (avoids an import cycle).
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_PATH = _REPO_ROOT / "config" / "config.yml"
_SECRETS_PATH = _REPO_ROOT / "config" / "secrets.env"

# Defaults so the system runs even with a minimal/empty config.yml.
DEFAULT_CONFIG = {
    "instance": {"name": "personal-os", "timezone": "UTC"},
    # data_dir: where authored/, generated/, conversations/ live. "" => repo root.
    "paths": {"data_dir": ""},
    # "" for answer => Claude Code default model. Cheap tiers pinned to Haiku.
    "models": {
        "answer": "",
        "summary": "claude-haiku-4-5-20251001",
        "digest": "claude-haiku-4-5-20251001",
    },
    "engine": {"command": "claude", "timeout_seconds": 120, "max_retries": 2},
    "embedding": {"model": "minishlab/potion-base-8M", "dim": 256},
    "snapshot": {
        "token_cap": 1800,      # hard cap (~1300-2000 target)
        "recent_days": 7,       # how far back "recent memory" looks
        "max_reminders": 12,
        "ttl_minutes": 720,     # rebuild if older than this (or sources changed / new day)
    },
    "recall": {
        "k": 6,                 # results returned to the model
        "candidate_k": 24,      # per-modality candidates before fusion
        "rrf_k": 60,            # Reciprocal Rank Fusion constant
        "weak_sim": 0.35,       # below this top cosine sim => flag "no strong matches"
    },
    "capture": {"store_raw_transcript": False, "max_input_chars": 4000},
    "telegram": {"enabled": True, "poll_timeout": 50},
    "digest": {"hour": 7, "minute": 30, "recent_days": 3},
    # active memory: auto-learn from chat (Tier 1) + timed reminders.
    "active_memory": {"enabled": True, "default_lead_minutes": 60},
    # sessions: per-topic short-term context buffers (the only thing /clear clears).
    "sessions": {"enabled": True, "max_turns": 10, "daily_clear": "04:00"},
    # voice: transcribe Telegram voice notes via OpenRouter's transcription endpoint.
    "voice": {"enabled": True, "provider": "openrouter",
              "model": "openai/whisper-large-v3", "language": ""},
    # runtime: machine-managed block (set via set_runtime); never hand-edit.
    "runtime": {"telegram_chat_id": None},
}


def _deep_merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


@lru_cache(maxsize=1)
def load_config() -> dict:
    user = {}
    if _CONFIG_PATH.exists():
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            user = yaml.safe_load(f) or {}
    return _deep_merge(DEFAULT_CONFIG, user)


@lru_cache(maxsize=1)
def load_secrets() -> dict:
    """Parse KEY=VALUE lines from secrets.env (dotenv-lite, no extra dependency).
    Environment variables of the same name take precedence."""
    secrets: dict[str, str] = {}
    if _SECRETS_PATH.exists():
        for raw in _SECRETS_PATH.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            secrets[key.strip()] = val.strip().strip('"').strip("'")
    for key in ("TELEGRAM_BOT_TOKEN", "ANTHROPIC_API_KEY"):
        if os.environ.get(key):
            secrets[key] = os.environ[key]
    return secrets


def get_secret(name: str, default=None):
    val = load_secrets().get(name)
    return val if val else default


def instance_name() -> str:
    return str(load_config().get("instance", {}).get("name") or "personal-os")


def timezone() -> str:
    """IANA timezone for interpreting natural times + firing reminders."""
    return str((load_config().get("instance", {}) or {}).get("timezone") or "UTC")


def model_for(tier: str) -> str:
    """Resolve a tier name to a model id. "" => engine default model."""
    return str((load_config().get("models", {}) or {}).get(tier, "") or "")


def runtime(key: str, default=None):
    """Read a machine-managed runtime value (e.g. telegram_chat_id)."""
    return (load_config().get("runtime", {}) or {}).get(key, default)


def reload() -> None:
    """Clear caches after config.yml / secrets.env change at runtime."""
    load_config.cache_clear()
    load_secrets.cache_clear()


import re as _re  # noqa: E402  (local helper use only)


def _yaml_scalar(v) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v)
    if s == "" or s.strip() != s or _re.search(r"[:#\[\]{}&*?|<>=!%@`\"']", s):
        return '"' + s.replace('"', '\\"') + '"'
    return s


def _render_runtime_block(values: dict) -> list[str]:
    lines = ["runtime:   # machine-managed by set_runtime() — do not hand-edit"]
    if not values:
        lines.append("  telegram_chat_id: null")
    for k, v in values.items():
        lines.append(f"  {k}: {_yaml_scalar(v)}")
    return lines


def set_runtime(key: str, value) -> None:
    """Persist a machine-managed runtime value by rewriting ONLY the `runtime:` block
    of config.yml textually — every other line/comment is preserved byte-for-byte
    (principle 1: never silently overwrite the human's authored config). Used e.g. to
    remember the Telegram chat_id on first contact."""
    current = dict(load_config().get("runtime", {}) or {})
    current[key] = value
    block = _render_runtime_block(current)

    text = _CONFIG_PATH.read_text(encoding="utf-8") if _CONFIG_PATH.exists() else ""
    lines = text.splitlines()

    start = next(
        (i for i, ln in enumerate(lines) if _re.match(r"^runtime:\s*(#.*)?$", ln)), None
    )
    if start is None:
        new_lines = lines[:]
        if new_lines and new_lines[-1].strip() != "":
            new_lines.append("")
        new_lines += block
    else:
        end = len(lines)
        for j in range(start + 1, len(lines)):
            ln = lines[j]
            if ln and not ln[0].isspace():  # next top-level key/comment ends the block
                end = j
                break
        new_lines = lines[:start] + block + lines[end:]

    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG_PATH.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    reload()
