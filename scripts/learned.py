"""Tier-1 auto-learned memory (machine-owned, instant, frictionless).

When you mention a like/dislike, a stray idea, or a rule in conversation, the extractor
files it here immediately — and it's used right away (the snapshot renders active items).
This is generated/ (machine-owned), so auto-writing it never violates principle 1.

Tier 2 is your authored canon. promote(id) APPENDS a confirmed item into the relevant
authored file under a clearly-marked "Auto-learned (confirmed)" section — this is the
ONLY path that touches authored content, and it runs only on your explicit approval
(/keep in Telegram), satisfying "agent proposes, human approves" (principle 7). It only
ever appends; it never rewrites your existing text. drop(id) discards a candidate.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from . import paths as _paths

PREFERENCE, IDEA, RULE = "preference", "idea", "rule"

_AUTHORED_TARGET = {PREFERENCE: "preferences.md", IDEA: "ideas.md", RULE: "dos-and-donts.md"}
_SECTION = "## Auto-learned (confirmed via Jarvis)"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _mk_id(kind: str, text: str) -> str:
    return hashlib.sha1(f"{kind}|{text.strip().lower()}".encode("utf-8")).hexdigest()[:6]


def _load() -> list[dict]:
    p = _paths.learned_file()
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8")) or []
    except (json.JSONDecodeError, OSError):
        return []


def _save(items: list[dict]) -> None:
    p = _paths.learned_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


def add(kind: str, text: str, *, polarity: str | None = None, rule_kind: str | None = None,
        source: str = "terminal") -> dict | None:
    text = (text or "").strip()
    if not text or kind not in _AUTHORED_TARGET:
        return None
    iid = _mk_id(kind, text)
    items = _load()
    existing = next((it for it in items if it["id"] == iid), None)
    if existing:
        return existing  # dedup; also respects a prior drop/promote (won't re-add)
    item = {"id": iid, "type": kind, "text": text, "polarity": polarity,
            "rule_kind": rule_kind, "created_utc": _now_iso(), "source": source,
            "status": "active"}
    items.append(item)
    _save(items)
    return item


def list_active(kind: str | None = None) -> list[dict]:
    return [it for it in _load() if it["status"] == "active" and (kind is None or it["type"] == kind)]


def pending() -> list[dict]:
    """Active, unconfirmed items awaiting promote/drop (shown in the digest)."""
    return list_active()


def _set_status(iid: str, status: str) -> dict | None:
    items = _load()
    for it in items:
        if it["id"] == iid:
            it["status"] = status
            _save(items)
            return it
    return None


def drop(iid: str) -> dict | None:
    return _set_status(iid, "dropped")


def _bullet(item: dict) -> str:
    t = item["text"]
    if item["type"] == PREFERENCE:
        return f"- ({'dislike' if item.get('polarity') == 'dislike' else 'like'}) {t}"
    if item["type"] == RULE:
        return f"- {'Never' if item.get('rule_kind') == 'dont' else 'Always'}: {t}"
    return f"- {t}"


def promote(iid: str) -> dict | None:
    """Append a confirmed item to its authored file (approval-gated) and reindex."""
    items = _load()
    item = next((it for it in items if it["id"] == iid and it["status"] == "active"), None)
    if not item:
        return None
    fname = _AUTHORED_TARGET[item["type"]]
    p = _paths.authored_file(fname)
    text = p.read_text(encoding="utf-8") if p.exists() else f"# {fname[:-3]}\n"
    if _SECTION not in text:
        text = text.rstrip() + f"\n\n{_SECTION}\n"
    text = text.rstrip() + f"\n{_bullet(item)}\n"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    item["status"] = "promoted"
    _save(items)
    try:
        from . import index
        index.index_file(p, index.AUTHORED)
    except Exception:
        pass
    return item


def render_for_snapshot() -> str:
    """Compact section of active (unconfirmed) learned items for the snapshot.
    Promoted items are already in authored files, so they're not repeated here."""
    active = list_active()
    if not active:
        return ""
    likes = [it["text"] for it in active if it["type"] == PREFERENCE and it.get("polarity") != "dislike"]
    dislikes = [it["text"] for it in active if it["type"] == PREFERENCE and it.get("polarity") == "dislike"]
    ideas = [it["text"] for it in active if it["type"] == IDEA]
    rules = [it["text"] for it in active if it["type"] == RULE]
    lines = []
    if likes:
        lines.append("Likes: " + "; ".join(likes))
    if dislikes:
        lines.append("Dislikes: " + "; ".join(dislikes))
    if ideas:
        lines.append("Ideas: " + "; ".join(ideas))
    if rules:
        lines.append("Rules: " + "; ".join(rules))
    return "\n".join(f"- {ln}" for ln in lines)
