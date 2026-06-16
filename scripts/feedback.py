"""Feedback loop: the user marks surfaced items useful/noise; we fold reactions into
generated/feedback.md so the daily digest's salience improves over time.

feedback.md is machine-owned (generated/), append-only, timestamped.
"""
from __future__ import annotations

from datetime import datetime, timezone

from . import paths as _paths

VERDICTS = ("useful", "noise")


def record_feedback(item: str, verdict: str, *, note: str = "", now: datetime | None = None) -> dict:
    verdict = (verdict or "").lower().strip()
    if verdict not in VERDICTS:
        raise ValueError(f"verdict must be one of {VERDICTS}")
    ts = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    p = _paths.feedback_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        p.write_text(
            f"---\ngenerated_at: {ts}\nkind: feedback-log\n---\n"
            f"# Feedback log — salience tuning for the daily digest\n\n"
            f"<!-- GENERATED — machine-owned; appended via /feedback -->\n\n",
            encoding="utf-8",
        )
    line = f"- [{ts}] **{verdict}** — {item.strip()}"
    if note.strip():
        line += f" — _note: {note.strip()}_"
    with open(p, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    return {"path": str(p), "recorded_at": ts, "verdict": verdict}


def load_feedback() -> str:
    p = _paths.feedback_file()
    return p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""
