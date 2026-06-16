"""STORAGE: capture every turn cheaply (the first job of memory).

After each turn: summarize it with the cheap tier (Haiku), append a condensed,
timestamped entry to today's daily log, and re-index that day's file. Capture is
exhaustive (not the agent's discretion) so nothing leaks, and BEST-EFFORT (it never
breaks the reply). If the summary engine call fails, the raw turn is stored as a
fallback marked `fallback` — we degrade, we never fabricate (principle 6).

Daily-log entry format is the frozen cross-module contract (D17g): each entry begins
with an HTML-comment marker carrying the citable source_id, which index.py and
snapshot.py read back verbatim.
"""
from __future__ import annotations

import fcntl
import hashlib
import os
from datetime import date, datetime, timedelta, timezone

from . import config as _config
from . import engine as _engine
from . import index as _index
from . import paths as _paths
from .index import DAILY_MARKER_RE

SUMMARY_SYS = (
    "You compress ONE conversation turn into a dense 1-3 sentence note for a personal "
    "memory log. Capture concrete facts about the user, their decisions, preferences, "
    "commitments, plans, and named entities. Write in the third person (\"The user ...\"). "
    "Do NOT invent anything that is not present in the turn. Output ONLY the note text, "
    "with no preamble, labels, or quotes."
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def _strip_frontmatter(text: str) -> str:
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            return text[end + 4 :].lstrip("\n")
    return text


def _summarize(user_msg: str, assistant_msg: str) -> tuple[str, bool]:
    """Return (summary, fallback). fallback=True means the engine failed and we stored
    a trimmed raw turn instead of a model summary (never fabricated)."""
    cap = _config.load_config().get("capture", {})
    maxc = int(cap.get("max_input_chars", 4000))
    turn = f"USER: {user_msg.strip()[:maxc]}\n\nASSISTANT: {assistant_msg.strip()[:maxc]}"
    try:
        note = _engine.complete(
            SUMMARY_SYS,
            "Summarize this conversation turn for the memory log.",
            tier="summary",
            data=turn,
            max_tokens=180,
        )
        return note.strip(), False
    except _engine.EngineError:
        gist = user_msg.strip().replace("\n", " ")[:300]
        return f"[unsummarized turn] The user said: {gist}", True


def _turn_key(date_str: str, user_msg: str, assistant_msg: str) -> str:
    h = hashlib.sha256(f"{date_str}\x00{user_msg}\x00{assistant_msg}".encode("utf-8"))
    return h.hexdigest()[:16]


def _make_source_id(date_str: str, seq: int) -> str:
    return f"daily/{date_str}#{seq:03d}"


def _ensure_header(content: str, date_str: str, now: datetime) -> str:
    if content.strip():
        return content
    return (
        f"---\ngenerated_at: {_iso(now)}\nkind: daily-log\ndate: {date_str}\n---\n"
        f"# Daily log — {date_str}\n\n"
        f"<!-- GENERATED — do not hand-edit; machine-owned (regenerable) -->\n\n"
    )


def capture(user_msg: str, assistant_msg: str, *, source: str = "terminal", now: datetime | None = None) -> dict:
    """Summarize + append + index one turn. Returns a result dict; raises nothing
    fatal to the caller is expected (callers should still wrap in try/except)."""
    now = now or _now()
    date_str = now.date().isoformat()
    log_path = _paths.daily_file(date_str)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    summary, fallback = _summarize(user_msg, assistant_msg)
    tkey = _turn_key(date_str, user_msg, assistant_msg)

    # flock the daily log around read-seq -> append (terminal + Telegram can race).
    with open(log_path, "a+", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            f.seek(0)
            content = f.read()
            if f"turn_key={tkey}" in content:
                return {"source_id": None, "log_path": str(log_path), "turn_key": tkey,
                        "indexed": False, "deduped": True, "summary": summary, "fallback": fallback}
            seq = len(DAILY_MARKER_RE.findall(content)) + 1
            source_id = _make_source_id(date_str, seq)
            header = _ensure_header(content, date_str, now)
            block = (
                f"<!-- turn source_id={source_id} turn_key={tkey} ts={_iso(now)} source={source} -->\n"
                f"{summary.strip()}\n\n"
            )
            if not content.strip():
                f.write(header)
            f.write(block)
            f.flush()
            os.fsync(f.fileno())
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)

    if _config.load_config().get("capture", {}).get("store_raw_transcript"):
        _store_raw(date_str, source_id, user_msg, assistant_msg, now, source)

    indexed = False
    try:
        _index.index_file(log_path, _index.DAILY)
        indexed = True
    except Exception:
        indexed = False  # index is best-effort; the durable daily log is the commit

    return {"source_id": source_id, "log_path": str(log_path), "turn_key": tkey,
            "indexed": indexed, "deduped": False, "summary": summary, "fallback": fallback}


def _store_raw(date_str, source_id, user_msg, assistant_msg, now, source) -> None:
    import json
    try:
        p = _paths.conversations_dir() / f"{date_str}.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        rec = {"ts": _iso(now), "source_id": source_id, "source": source,
               "user": user_msg, "assistant": assistant_msg}
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def capture_turn(user_msg: str, assistant_msg: str, conversation_id: str = "terminal") -> dict | None:
    """Wrapper the assistant calls after replying. Never raises (best-effort)."""
    source = conversation_id.split(":", 1)[0] if conversation_id else "terminal"
    try:
        return capture(user_msg, assistant_msg, source=source)
    except Exception:
        return None


def recent_summaries(days: int = 7, limit: int = 25) -> list[dict]:
    """Most-recent-first list of {date, source_id, text} parsed from recent daily logs.
    Used by snapshot.py to compose 'recent memory' (single-source: it reads the logs)."""
    today = date.today()
    out: list[dict] = []
    for delta in range(days):
        d = (today - timedelta(days=delta)).isoformat()
        p = _paths.daily_file(d)
        if not p.exists():
            continue
        body = _strip_frontmatter(p.read_text(encoding="utf-8", errors="replace"))
        matches = list(DAILY_MARKER_RE.finditer(body))
        for i, m in enumerate(matches):
            sid = m.group("sid")
            seg = body[m.end() : (matches[i + 1].start() if i + 1 < len(matches) else len(body))].strip()
            if seg:
                out.append({"date": d, "source_id": sid, "text": seg})
    out.sort(key=lambda e: (e["date"], e["source_id"]), reverse=True)
    return out[:limit]
