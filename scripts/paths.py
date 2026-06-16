"""Single source of truth for every filesystem path in personal-os (principle 3).

config + secrets travel with the engine (repo). authored/, generated/, conversations/
live under data_root (config.paths.data_dir, default = repo root) so a fresh instance
can point at its own data directory.
"""
from __future__ import annotations

from datetime import date as _date
from pathlib import Path

from . import config as _config

# Canonical authored filenames (the human-owned single sources of truth).
AUTHORED_FILES = [
    "about-me.md",
    "agent-persona.md",
    "dos-and-donts.md",
    "preferences.md",
    "priorities.md",
    "ideas.md",
    "reminders.md",
]


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def data_root() -> Path:
    d = (_config.load_config().get("paths", {}) or {}).get("data_dir") or ""
    return Path(d).expanduser().resolve() if d else repo_root()


# --- engine + config (with the repo) ---------------------------------------
def config_dir() -> Path:
    return repo_root() / "config"


def config_file() -> Path:
    return config_dir() / "config.yml"


def secrets_file() -> Path:
    return config_dir() / "secrets.env"


def agent_md() -> Path:
    return repo_root() / "AGENT.md"


# --- authored (human-owned) -------------------------------------------------
def authored_dir() -> Path:
    return data_root() / "authored"


def authored_file(name: str) -> Path:
    return authored_dir() / name


# --- generated (machine-owned) ----------------------------------------------
def generated_dir() -> Path:
    return data_root() / "generated"


def memory_dir() -> Path:
    return generated_dir() / "memory"


def daily_dir() -> Path:
    return memory_dir() / "daily"


def daily_file(d: str | None = None) -> Path:
    d = d or _date.today().isoformat()
    return daily_dir() / f"{d}.md"


def snapshot_file() -> Path:
    return memory_dir() / "snapshot.md"


def index_dir() -> Path:
    return memory_dir() / "index"


def index_db() -> Path:
    return index_dir() / "memory.db"


def index_lock() -> Path:
    return index_dir() / "memory.db.lock"


def engine_log() -> Path:
    # metadata-only engine call log; under generated/ => gitignored
    return index_dir() / "engine.log"


def digests_dir() -> Path:
    return generated_dir() / "digests"


def digest_file(d: str | None = None) -> Path:
    d = d or _date.today().isoformat()
    return digests_dir() / f"{d}.md"


def feedback_file() -> Path:
    return generated_dir() / "feedback.md"


def telegram_offset_file() -> Path:
    return generated_dir() / "telegram_offset.txt"


def digest_lock() -> Path:
    return generated_dir() / "digest.lock"


def digest_cron_log() -> Path:
    return generated_dir() / "digest-cron.log"


def conversations_dir() -> Path:
    return data_root() / "conversations"


def rel_to_data(path: Path) -> str:
    """Path relative to data_root for stable citations / source ids."""
    try:
        return str(Path(path).resolve().relative_to(data_root()))
    except ValueError:
        return str(path)


def ensure_dirs() -> None:
    for p in (authored_dir(), daily_dir(), index_dir(), digests_dir(), conversations_dir()):
        p.mkdir(parents=True, exist_ok=True)
