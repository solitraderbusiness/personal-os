"""INJECTION: the capped, cached identity snapshot (the second job of memory).

build_snapshot() composes a GENERATED projection of the authored identity files +
current priorities/reminders + the most recent memories, capped at ~1300-2000 tokens.
It is a derived cache (timestamped, marked generated) of single-source authored files,
NOT a duplication — each section names the authored source it came from (principle 2).

Caching: get_snapshot() rebuilds only when stale (file missing, a source changed
[fingerprint], or TTL exceeded), so the snapshot is built once per session and reused
across turns. Identity is NEVER trimmed; if identity alone exceeds the cap we keep it
and emit an honest over-cap warning rather than silently dropping load-bearing rules.
AGENT.md (the operating contract) is intentionally NOT here — assistant.py injects it
separately so it can never be trimmed under the cap (ADR-09).
"""
from __future__ import annotations

import hashlib
import math
import re
from datetime import datetime, timezone

from . import capture as _capture
from . import config as _config
from . import learned as _learned
from . import paths as _paths
from . import reminders as _reminders

# Authored files that form the never-dropped identity core.
IDENTITY_FILES = ["about-me.md", "agent-persona.md", "dos-and-donts.md"]


def est_tokens(text: str, chars_per_token: int = 4) -> int:
    """The single shared token estimator (no tokenizer dependency)."""
    return math.ceil(len(text or "") / max(1, chars_per_token))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _strip_comments(text: str) -> str:
    return re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL).strip()


def _read_authored(name: str) -> str:
    p = _paths.authored_file(name)
    if not p.exists():
        return ""
    return _strip_comments(p.read_text(encoding="utf-8", errors="replace"))


def _fingerprint(now: datetime) -> str:
    h = hashlib.sha256()
    for name in IDENTITY_FILES + ["priorities.md", "reminders.md"]:
        h.update(name.encode())
        h.update(_read_authored(name).encode("utf-8"))
    # include the day so the snapshot refreshes its "recent memory" daily
    h.update(now.date().isoformat().encode())
    recent = _capture.recent_summaries(
        days=int(_config.load_config().get("snapshot", {}).get("recent_days", 7)), limit=25
    )
    h.update(str(len(recent)).encode())
    if recent:
        h.update(recent[0]["source_id"].encode())
    return h.hexdigest()[:16]


def _section(title: str, body: str) -> str:
    body = body.strip()
    if not body:
        return ""
    return f"## {title}\n{body}\n"


def build_snapshot(*, now: datetime | None = None) -> dict:
    now = now or _now()
    cfg = _config.load_config().get("snapshot", {})
    cap = int(cfg.get("token_cap", 1800))
    cpt = int(cfg.get("chars_per_token", 4)) if "chars_per_token" in cfg else 4

    # --- identity core (never dropped) ---
    identity_parts = []
    sources = []
    for name in IDENTITY_FILES:
        body = _read_authored(name)
        if body:
            identity_parts.append(_section(_title_for(name), body))
            sources.append(f"authored/{name}")
    for name in ("priorities.md", "reminders.md"):
        body = _read_authored(name)
        if body and cfg.get(f"include_{name.split('.')[0]}", True):
            identity_parts.append(_section(_title_for(name), body))
            sources.append(f"authored/{name}")
    identity_text = "\n".join(p for p in identity_parts if p)

    # --- active memory: auto-learned (Tier 1) + upcoming reminders (always included) ---
    learned_text = _learned.render_for_snapshot()
    up_text = _reminders.format_upcoming(8)
    if learned_text:
        identity_text += "\n## Things you've recently told me\n" + learned_text + "\n"
    if up_text:
        identity_text += "\n## Upcoming reminders\n" + up_text + "\n"

    # --- recent memory (trimmed to fit under the cap) ---
    recent = _capture.recent_summaries(
        days=int(cfg.get("recent_days", 7)), limit=int(cfg.get("max_reminders", 25))
    )
    identity_tokens = est_tokens(identity_text, cpt)
    budget = cap - identity_tokens - 40  # reserve for headers
    mem_lines, omitted = [], 0
    for e in recent:
        line = f"- {e['text'].strip()}"
        if est_tokens("\n".join(mem_lines + [line]), cpt) <= budget:
            mem_lines.append(line)
        else:
            omitted += 1
    over_cap = identity_tokens > cap

    # --- assemble body ---
    parts = ["# Identity & standing context\n", identity_text]
    if mem_lines:
        parts.append("\n## Recently discussed (most recent first)\n" + "\n".join(mem_lines))
    if over_cap:
        parts.append(
            "\n> NOTE: authored identity exceeds the snapshot token cap; it is kept in "
            "full (never trimmed). Consider tightening the authored files."
        )
    elif omitted:
        parts.append(f"\n> ({omitted} older memory item(s) omitted to stay under the token cap.)")
    body = "\n".join(p for p in parts if p).strip() + "\n"

    fp = _fingerprint(now)
    token_est = est_tokens(body, cpt)
    front = (
        f"---\ngenerated_at: {now.isoformat(timespec='seconds')}\n"
        f"token_estimate: {token_est}\ntoken_cap: {cap}\nfingerprint: {fp}\n"
        f"over_cap: {str(over_cap).lower()}\n"
        f"sources: [{', '.join(sources) if sources else ''}]\n---\n"
    )
    full = front + "<!-- GENERATED — do not hand-edit; machine-owned (regenerable) -->\n\n" + body

    out = _paths.snapshot_file()
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".md.tmp")
    tmp.write_text(full, encoding="utf-8")
    tmp.replace(out)
    return {"body": body, "path": str(out), "generated_at": now.isoformat(timespec="seconds"),
            "token_estimate": token_est, "token_cap": cap, "fingerprint": fp,
            "omitted": omitted, "over_cap": over_cap, "sources": sources}


def _title_for(name: str) -> str:
    return {
        "about-me.md": "About me",
        "agent-persona.md": "How you should behave (persona)",
        "dos-and-donts.md": "Do's and don'ts",
        "priorities.md": "Current priorities",
        "reminders.md": "Active reminders",
    }.get(name, name)


def is_stale(*, now: datetime | None = None) -> bool:
    now = now or _now()
    out = _paths.snapshot_file()
    if not out.exists():
        return True
    text = out.read_text(encoding="utf-8", errors="replace")
    m_fp = re.search(r"^fingerprint:\s*(\S+)", text, re.MULTILINE)
    if not m_fp or m_fp.group(1) != _fingerprint(now):
        return True
    m_ts = re.search(r"^generated_at:\s*(\S+)", text, re.MULTILINE)
    ttl_h = float(_config.load_config().get("snapshot", {}).get("ttl_minutes", 720)) / 60.0
    if m_ts:
        try:
            gen = datetime.fromisoformat(m_ts.group(1))
            if (now - gen).total_seconds() > ttl_h * 3600:
                return True
        except ValueError:
            return True
    return False


def get_snapshot(*, force: bool = False, now: datetime | None = None) -> dict:
    if force or is_stale(now=now):
        return build_snapshot(now=now)
    text = _paths.snapshot_file().read_text(encoding="utf-8", errors="replace")
    body = _capture._strip_frontmatter(text)
    body = re.sub(r"^<!--.*?-->\n+", "", body, flags=re.DOTALL)
    return {"body": body.strip() + "\n", "path": str(_paths.snapshot_file()), "cached": True}


def snapshot_text(*, now: datetime | None = None) -> str:
    """The identity text the runtime injects each turn (built once, then cached)."""
    return get_snapshot(now=now).get("body", "")


if __name__ == "__main__":
    import json
    s = build_snapshot()
    print(json.dumps({k: v for k, v in s.items() if k != "body"}, indent=2))
    print("---\n" + s["body"])
