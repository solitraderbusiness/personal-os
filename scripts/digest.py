"""PROACTIVE layer: the daily digest (run unattended by cron).

generate_digest() reads the user's priorities + reminders (authored) + recent daily
logs + feedback (generated), asks the cheap engine tier to decide what's important,
what they might be forgetting, and what they said they'd do and haven't — then writes
a timestamped digest to generated/digests/YYYY-MM-DD.md and pushes it to Telegram.

It only READS authored files (never edits them — principle 1). All inputs are passed
as untrusted DATA. If the engine fails, it still writes a digest file noting the error
so the failure is OBSERVABLE (and never silently skipped). The user's reactions
(/feedback useful|noise) are folded back in to tune future salience.

Run: venv/bin/python -m scripts.digest --date today [--push|--no-push]
"""
from __future__ import annotations

import argparse
import re
from datetime import date, datetime, timezone

from . import capture as _capture
from . import config as _config
from . import engine as _engine
from . import feedback as _feedback
from . import learned as _learned
from . import paths as _paths
from . import reminders as _reminders

DIGEST_SYS = (
    "You write a short, calm daily brief for the user of a personal memory assistant. "
    "Use ONLY the provided DATA (their priorities, reminders, recent activity, and "
    "feedback). Produce up to three sections, omitting any that have nothing:\n"
    "- **Top of mind** — what matters most today given their stated priorities.\n"
    "- **Don't forget** — reminders or commitments they may be dropping.\n"
    "- **Loose threads** — things they said they'd do that haven't recurred lately.\n"
    "Be brief and specific, reference concrete items, and never invent anything not in "
    "the DATA. If activity is light, say so plainly in one line. Respect the feedback: "
    "do NOT resurface items the user marked 'noise'. Output only the brief (markdown)."
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _read_authored(name: str) -> str:
    p = _paths.authored_file(name)
    if not p.exists():
        return ""
    txt = re.sub(r"<!--.*?-->", "", p.read_text(encoding="utf-8", errors="replace"), flags=re.DOTALL)
    return txt.strip()


def _gather_sources(d: str) -> tuple[str, dict]:
    cfg = _config.load_config().get("digest", {})
    days = int(cfg.get("recent_days", 3))
    pri = _read_authored("priorities.md")
    rem = _read_authored("reminders.md")
    recent = _capture.recent_summaries(days=days, limit=40)
    fb = _feedback.load_feedback()

    blocks = [f"TODAY: {d}"]
    if pri:
        blocks.append("PRIORITIES (authored/priorities.md):\n" + pri)
    if rem:
        blocks.append("REMINDERS (authored/reminders.md):\n" + rem)
    if recent:
        lines = "\n".join(f"- ({e['source_id']}) {e['text']}" for e in recent)
        blocks.append(f"RECENT ACTIVITY (last {days} day(s), newest first):\n" + lines)
    else:
        blocks.append("RECENT ACTIVITY: none in the recent window.")
    if fb.strip():
        blocks.append("FEEDBACK (user-marked useful/noise — respect this):\n" + fb.strip()[:2000])
    meta = {"priorities": bool(pri), "reminders": bool(rem),
            "recent_items": len(recent), "feedback": bool(fb.strip())}
    return "\n\n".join(blocks), meta


def generate_digest(d: str | None = None, *, push: bool = True) -> dict:
    now = _now()
    d = d or now.date().isoformat()
    sources, meta = _gather_sources(d)

    engine_ok = True
    try:
        body = _engine.complete(
            DIGEST_SYS, f"Write the daily brief for {d}.",
            tier="digest", data=sources, max_tokens=600,
        )
    except _engine.EngineError as exc:
        engine_ok = False
        body = (
            f"_Digest could not be generated: engine error ({exc.kind})._\n\n"
            f"This is an observable failure, not a silent skip. Check the engine "
            f"(e.g. `claude` CLI auth) and the cron log at "
            f"`generated/digest-cron.log`."
        )

    # Deterministic active-memory sections appended to the brief.
    ups = _reminders.format_upcoming(10)
    if ups:
        body += "\n\n## ⏰ Upcoming reminders\n" + ups
    pend = _learned.pending()
    if pend:
        body += "\n\n## 📥 Learned — to confirm (reply /keep <id> or /drop <id>)\n" + "\n".join(
            f"- [{it['id']}] {it['type']}: {it['text']}" for it in pend
        )

    out = _paths.digest_file(d)
    out.parent.mkdir(parents=True, exist_ok=True)
    front = (
        f"---\ngenerated_at: {now.isoformat(timespec='seconds')}\nkind: digest\n"
        f"date: {d}\nengine_ok: {str(engine_ok).lower()}\n"
        f"sources: {meta}\n---\n"
    )
    out.write_text(
        front + "<!-- GENERATED — machine-owned (regenerable) -->\n\n"
        f"# Daily digest — {d}\n\n{body.strip()}\n",
        encoding="utf-8",
    )

    pushed = False
    if push:
        try:
            from . import telegram_bot
            if telegram_bot._token() and _config.runtime("telegram_chat_id") is not None:
                pushed = telegram_bot.send_message(f"🗓️ Daily digest — {d}\n\n{body.strip()}")
        except Exception:
            pushed = False

    # index the digest so it becomes recallable too (best-effort)
    try:
        from . import index
        index.index_file(out, index.DIGEST)
    except Exception:
        pass

    return {"date": d, "path": str(out), "generated_at": now.isoformat(timespec="seconds"),
            "engine_ok": engine_ok, "pushed": pushed, "sources": meta}


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate the personal-os daily digest.")
    ap.add_argument("--date", default="today", help="YYYY-MM-DD or 'today'")
    ap.add_argument("--push", dest="push", action="store_true", default=True)
    ap.add_argument("--no-push", dest="push", action="store_false")
    args = ap.parse_args()
    d = None if args.date == "today" else args.date
    res = generate_digest(d, push=args.push)
    import json
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
