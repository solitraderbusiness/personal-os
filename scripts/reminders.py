"""Timed reminders engine (timezone-aware, idempotent).

Reminders are stored in UTC (machine-owned generated/). A frequent cron tick calls
check_and_notify(), which pushes a Telegram nudge `lead_minutes` before each due time
and marks it notified so it never double-fires. Display converts back to the user's
local timezone (config.instance.timezone). If a push fails it is retried on the next
tick; once well past due it is marked notified (missed) to stop retrying.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import config as _config
from . import paths as _paths

_GRACE = timedelta(hours=6)  # after due+grace, stop retrying a missed reminder


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _tz() -> ZoneInfo:
    try:
        return ZoneInfo(_config.timezone())
    except Exception:
        return ZoneInfo("UTC")


def local_to_utc(naive_local_iso: str) -> str | None:
    """Convert a naive local 'YYYY-MM-DDTHH:MM[:SS]' to a UTC ISO string."""
    if not naive_local_iso:
        return None
    s = naive_local_iso.strip().replace(" ", "T")
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s, fmt)
            break
        except ValueError:
            dt = None
    if dt is None:
        return None
    return dt.replace(tzinfo=_tz()).astimezone(timezone.utc).isoformat(timespec="seconds")


def _fmt_local(utc_iso: str) -> str:
    try:
        dt = datetime.fromisoformat(utc_iso).astimezone(_tz())
        return dt.strftime("%a %Y-%m-%d %H:%M")
    except ValueError:
        return utc_iso


def _load() -> list[dict]:
    p = _paths.reminders_file()
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8")) or []
    except (json.JSONDecodeError, OSError):
        return []


def _save(items: list[dict]) -> None:
    p = _paths.reminders_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


def add(text: str, due_utc: str, *, lead_minutes: int | None = None, source: str = "terminal") -> dict | None:
    text = (text or "").strip()
    if not text or not due_utc:
        return None
    if lead_minutes is None:
        lead_minutes = int(_config.load_config().get("active_memory", {}).get("default_lead_minutes", 60))
    iid = hashlib.sha1(f"{text.lower()}|{due_utc}".encode("utf-8")).hexdigest()[:6]
    items = _load()
    if any(it["id"] == iid for it in items):
        return next(it for it in items if it["id"] == iid)
    item = {"id": iid, "text": text, "due_utc": due_utc, "lead_minutes": int(lead_minutes),
            "created_utc": _now_utc().isoformat(timespec="seconds"), "source": source,
            "notified": False, "status": "active"}
    items.append(item)
    _save(items)
    return item


def upcoming(limit: int = 10) -> list[dict]:
    now = _now_utc()
    out = [it for it in _load() if it["status"] == "active"
           and datetime.fromisoformat(it["due_utc"]) >= now]
    out.sort(key=lambda it: it["due_utc"])
    return out[:limit]


def cancel(iid: str) -> dict | None:
    items = _load()
    for it in items:
        if it["id"] == iid:
            it["status"] = "cancelled"
            _save(items)
            return it
    return None


def format_upcoming(limit: int = 10) -> str:
    ups = upcoming(limit)
    if not ups:
        return ""
    return "\n".join(f"- {it['text']} — {_fmt_local(it['due_utc'])}" for it in ups)


def check_and_notify(now_utc: datetime | None = None) -> int:
    """Push due reminders (lead before due) and mark them notified. Returns count sent."""
    now = now_utc or _now_utc()
    items = _load()
    sent = 0
    dirty = False
    for it in items:
        if it["status"] != "active" or it["notified"]:
            continue
        due = datetime.fromisoformat(it["due_utc"])
        notify_at = due - timedelta(minutes=int(it["lead_minutes"]))
        if now < notify_at:
            continue
        if now > due + _GRACE:
            it["notified"] = True  # missed window; stop retrying
            dirty = True
            continue
        mins = max(0, int((due - now).total_seconds() // 60))
        when = "now" if mins <= 1 else f"in ~{mins} min"
        msg = f"⏰ Reminder ({when}): {it['text']}\n   at {_fmt_local(it['due_utc'])}"
        ok = False
        try:
            from . import telegram_bot
            ok = telegram_bot.send_message(msg)
        except Exception:
            ok = False
        if ok:
            it["notified"] = True
            dirty = True
            sent += 1
        # if not ok: leave un-notified to retry on the next tick (until grace passes)
    if dirty:
        _save(items)
    return sent


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd == "check":
        print(f"notified {check_and_notify()} reminder(s)")
    elif cmd == "list":
        print(format_upcoming(20) or "(no upcoming reminders)")
