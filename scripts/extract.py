"""Active capture: from one turn, get the daily-log summary AND structured memory items
in a SINGLE cheap (Haiku) call, then route the items into Tier-1 stores.

Extraction is conservative — only items explicitly supported by the turn — and
best-effort: on any engine/parse failure it degrades to a plain summary with no items
(it never fabricates). Relative times ("tomorrow 10am") are resolved against the user's
local now + timezone and stored as UTC by the reminders engine.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from . import config as _config
from . import engine as _engine
from . import learned as _learned
from . import reminders as _reminders

ANALYZE_SYS = (
    "You process ONE conversation turn for a personal memory assistant. Respond with a "
    "SINGLE JSON object and nothing else, with these keys:\n"
    '  "summary": a dense 1-3 sentence third-person note of the turn (facts, decisions, context).\n'
    '  "preferences": array of {"text": "...", "polarity": "like"|"dislike"} the user EXPRESSED.\n'
    '  "ideas": array of strings — ideas the user floated worth remembering.\n'
    '  "rules": array of {"text": "...", "kind": "do"|"dont"} — explicit standing instructions '
    'to you (e.g. "never suggest n8n" -> kind "dont").\n'
    '  "reminders": array of {"text": "...", "datetime_local": "YYYY-MM-DDTHH:MM" or null, '
    '"lead_minutes": integer or null} — things to be reminded about at a time.\n'
    "Rules: include ONLY items clearly supported by THIS turn; use empty arrays otherwise. "
    "NEVER invent. Resolve relative times (\"tomorrow 10am\", \"in 2 hours\") using the current "
    "local date/time given to you. Output ONLY the JSON object."
)


def _local_now() -> datetime:
    try:
        tz = ZoneInfo(_config.timezone())
    except Exception:
        tz = ZoneInfo("UTC")
    return datetime.now(timezone.utc).astimezone(tz)


def _parse_json(text: str) -> dict | None:
    text = (text or "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # find the first balanced {...} block
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def analyze_turn(user_msg: str, assistant_msg: str, *, now_local: datetime | None = None) -> dict:
    now_local = now_local or _local_now()
    cap = _config.load_config().get("capture", {})
    maxc = int(cap.get("max_input_chars", 4000))
    turn = f"USER: {user_msg.strip()[:maxc]}\n\nASSISTANT: {assistant_msg.strip()[:maxc]}"
    sys = (
        ANALYZE_SYS
        + f"\n\nCurrent local date/time: {now_local.strftime('%A %Y-%m-%d %H:%M')} "
        + f"({_config.timezone()})."
    )
    empty = {"summary": "", "preferences": [], "ideas": [], "rules": [], "reminders": [], "fallback": True}
    try:
        raw = _engine.complete(sys, "Analyze this turn.", tier="summary", data=turn, max_tokens=500)
    except _engine.EngineError:
        gist = user_msg.strip().replace("\n", " ")[:300]
        empty["summary"] = f"[unsummarized turn] The user said: {gist}"
        return empty
    obj = _parse_json(raw)
    if not isinstance(obj, dict):
        empty["summary"] = raw.strip()[:600] or "[turn captured]"
        return empty
    return {
        "summary": str(obj.get("summary") or "").strip() or "[turn captured]",
        "preferences": obj.get("preferences") or [],
        "ideas": obj.get("ideas") or [],
        "rules": obj.get("rules") or [],
        "reminders": obj.get("reminders") or [],
        "fallback": False,
    }


def ingest(items: dict, *, source: str = "terminal") -> dict:
    """Route extracted items into Tier-1 stores (learned + reminders). Best-effort."""
    counts = {"preferences": 0, "ideas": 0, "rules": 0, "reminders": 0}
    try:
        for p in items.get("preferences", []):
            if isinstance(p, dict) and p.get("text"):
                if _learned.add(_learned.PREFERENCE, p["text"], polarity=p.get("polarity"), source=source):
                    counts["preferences"] += 1
        for i in items.get("ideas", []):
            t = i.get("text") if isinstance(i, dict) else i
            if t and _learned.add(_learned.IDEA, t, source=source):
                counts["ideas"] += 1
        for r in items.get("rules", []):
            if isinstance(r, dict) and r.get("text"):
                if _learned.add(_learned.RULE, r["text"], rule_kind=r.get("kind"), source=source):
                    counts["rules"] += 1
        for rem in items.get("reminders", []):
            if not isinstance(rem, dict) or not rem.get("text"):
                continue
            due = _reminders.local_to_utc(rem.get("datetime_local"))
            if not due:
                continue  # no resolvable time -> don't fabricate one (still in the daily log)
            lead = rem.get("lead_minutes")
            if _reminders.add(rem["text"], due, lead_minutes=lead, source=source):
                counts["reminders"] += 1
    except Exception:
        pass
    return counts
