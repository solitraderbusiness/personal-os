"""Per-session short-term context buffers (Phase 8).

Each conversation thread — a Telegram topic, a DM, or the terminal — is a separate
SESSION keyed by a session_id (e.g. "telegram:-100123:5" for chat -100123 / topic 5).
A small capped rolling buffer of recent turns gives the assistant conversational
continuity WITHIN a thread, without letting context grow unbounded.

CRITICAL INVARIANT: long-term memory (daily logs, learned store, index) is written on
every turn independently of this buffer. So clearing a buffer (/clear, or the daily
auto-clear) NEVER loses anything — you can always recall or resume a topic later. The
buffer is the ONLY thing /clear clears.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from . import config as _config
from . import paths as _paths


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def enabled() -> bool:
    return bool(_config.load_config().get("sessions", {}).get("enabled", True))


def _max_turns() -> int:
    return int(_config.load_config().get("sessions", {}).get("max_turns", 10))


def _load() -> dict:
    p = _paths.sessions_file()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8")) or {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save(d: dict) -> None:
    p = _paths.sessions_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


def append_turn(session_id: str, user_msg: str, assistant_msg: str) -> None:
    if not enabled() or not session_id:
        return
    d = _load()
    s = d.setdefault(session_id, {"turns": [], "updated_utc": None})
    s["turns"].append({"u": user_msg, "a": assistant_msg, "ts": _now_iso()})
    s["turns"] = s["turns"][-_max_turns():]
    s["updated_utc"] = _now_iso()
    _save(d)


def get_context(session_id: str, max_chars: int = 4000) -> str:
    """Rendered recent turns for this session (capped), for conversational continuity."""
    if not enabled() or not session_id:
        return ""
    s = _load().get(session_id)
    if not s or not s.get("turns"):
        return ""
    blocks = [f"You: {t['u']}\nAssistant: {t['a']}" for t in s["turns"]]
    text = "\n\n".join(blocks)
    return text[-max_chars:]


def clear(session_id: str) -> int:
    """Clear one session's buffer. Returns the number of turns dropped."""
    d = _load()
    s = d.get(session_id)
    n = len(s.get("turns", [])) if s else 0
    if s:
        d[session_id] = {"turns": [], "updated_utc": _now_iso()}
        _save(d)
    return n


def clear_all() -> int:
    """Clear EVERY session buffer (the daily 4am clear). Returns total turns dropped."""
    d = _load()
    total = sum(len(s.get("turns", [])) for s in d.values())
    for k in list(d.keys()):
        d[k] = {"turns": [], "updated_utc": _now_iso()}
    _save(d)
    return total


def list_sessions() -> list[dict]:
    return [{"session_id": k, "turns": len(v.get("turns", [])), "updated_utc": v.get("updated_utc")}
            for k, v in _load().items()]


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    if cmd == "clear-all":
        print(f"cleared {clear_all()} buffered turn(s) across all sessions")
    elif cmd == "clear" and len(sys.argv) > 2:
        print(f"cleared {clear(sys.argv[2])} turn(s) from {sys.argv[2]}")
    else:
        for s in list_sessions():
            print(f"  {s['session_id']}: {s['turns']} turns (updated {s['updated_utc']})")
