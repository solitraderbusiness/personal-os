"""Telegram front-door — the single place you talk to personal-os from anywhere.

A lightweight long-poll bot (stdlib + requests; no heavy framework). It:
  - reads the bot token ONLY from gitignored secrets.env (never logs it / the URL);
  - is restricted to a SINGLE authorized chat — the first sender becomes the owner
    (stored in config runtime); every other chat is dropped BEFORE the engine is
    ever called (no cost, no injection surface);
  - relays owner messages through the same assistant.respond() loop as the terminal;
  - exposes send_message(), reused by the daily digest to push to you.

Run (typically under tmux):   venv/bin/python -m scripts.telegram_bot
"""
from __future__ import annotations

import re
import sys
import time

import requests

from . import assistant as _assistant
from . import config as _config
from . import feedback as _feedback
from . import learned as _learned
from . import paths as _paths
from . import reminders as _reminders
from . import sessions as _sessions
from . import transcribe as _transcribe

TG_MAX = 4000  # Telegram hard limit is 4096; leave headroom
HELP = (
    "personal-os — your private memory assistant.\n\n"
    "Just send a message and I'll answer using your memory (with sources). I quietly "
    "learn your likes/ideas/rules and pick up reminders as we talk.\n\n"
    "In a forum group, each TOPIC is its own thread with its own short-term context.\n\n"
    "Commands:\n"
    "  /learned          — show things I've learned, pending your confirmation\n"
    "  /keep <id…>       — save those learned items into your permanent files\n"
    "  /drop <id…>       — discard those learned items\n"
    "  /reminders        — list your upcoming reminders\n"
    "  /clear            — clear THIS thread's short-term context (memory is kept)\n"
    "  /feedback useful|noise <item> — tune the daily digest\n"
    "  /whoami           — show this chat / topic id\n"
    "  /help             — this help"
)


def _log(msg: str) -> None:
    """Stderr log. Messages are built by us and never contain the token or API URL."""
    print(f"[telegram] {msg}", file=sys.stderr, flush=True)


def _token() -> str | None:
    return _config.get_secret("TELEGRAM_BOT_TOKEN")


def _redact(text: str, token: str | None) -> str:
    return text.replace(token, "***") if token else text


def _split(text: str, limit: int = TG_MAX) -> list[str]:
    text = text or "(empty)"
    if len(text) <= limit:
        return [text]
    # hard-wrap any over-long line first so nothing is dropped
    lines: list[str] = []
    for line in text.split("\n"):
        while len(line) > limit:
            lines.append(line[:limit])
            line = line[limit:]
        lines.append(line)
    chunks, cur = [], ""
    for line in lines:
        if cur and len(cur) + len(line) + 1 > limit:
            chunks.append(cur)
            cur = line
        else:
            cur = f"{cur}\n{line}" if cur else line
    if cur:
        chunks.append(cur)
    return chunks


def send_message(text: str, chat_id=None, thread_id=None) -> bool:
    """Send a message to the owner chat (or `chat_id`), optionally inside a forum topic
    (`thread_id`). Returns True on success. NEVER logs the token or the API URL."""
    token = _token()
    if not token:
        _log("no TELEGRAM_BOT_TOKEN configured; cannot send")
        return False
    chat_id = chat_id if chat_id is not None else _config.runtime("telegram_chat_id")
    if chat_id is None:
        _log("no chat_id known yet; message not sent")
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    ok = True
    for chunk in _split(text):
        payload = {"chat_id": chat_id, "text": chunk}
        if thread_id is not None:
            payload["message_thread_id"] = thread_id
        try:
            r = requests.post(url, json=payload, timeout=30)
            if r.status_code != 200:
                _log(f"send failed: HTTP {r.status_code}")  # no url/token/body
                ok = False
        except requests.RequestException as exc:
            _log(f"send error: {type(exc).__name__}")  # never str(exc) (may embed url)
            ok = False
    return ok


def send_typing(chat_id, thread_id=None) -> None:
    """Show a 'typing…' indicator (best-effort) while the engine thinks."""
    token = _token()
    if not token or chat_id is None:
        return
    try:
        payload = {"chat_id": chat_id, "action": "typing"}
        if thread_id is not None:
            payload["message_thread_id"] = thread_id
        requests.post(f"https://api.telegram.org/bot{token}/sendChatAction", json=payload, timeout=10)
    except requests.RequestException:
        pass


def _download_file(token: str, file_id: str) -> bytes | None:
    """Download a Telegram file by id. The URL embeds the token, so it is never logged."""
    try:
        r = requests.get(f"https://api.telegram.org/bot{token}/getFile",
                         params={"file_id": file_id}, timeout=30)
        if r.status_code != 200:
            return None
        fp = (r.json().get("result") or {}).get("file_path")
        if not fp:
            return None
        fr = requests.get(f"https://api.telegram.org/file/bot{token}/{fp}", timeout=120)
        return fr.content if fr.status_code == 200 else None
    except requests.RequestException:
        return None


def _audio_format(msg: dict, obj: dict) -> str:
    if "voice" in msg:
        return "ogg"  # Telegram voice notes are OGG/Opus
    mime = (obj.get("mime_type") or "").lower()
    for needle, fmt in (("mpeg", "mp3"), ("mp3", "mp3"), ("m4a", "m4a"), ("mp4", "m4a"),
                        ("aac", "m4a"), ("wav", "wav"), ("webm", "webm"), ("flac", "flac")):
        if needle in mime:
            return fmt
    return "ogg"


def _voice_to_text(token: str, msg: dict, cid, thread_id) -> str | None:
    """Download + transcribe a voice/audio message. Echoes what was heard. Returns text."""
    obj = msg.get("voice") or msg.get("audio")
    if not obj:
        return None
    _log(f"voice received: dur={obj.get('duration','?')}s mime={obj.get('mime_type','?')}")
    send_typing(cid, thread_id)
    audio = _download_file(token, obj["file_id"])
    if not audio:
        _log("voice: download FAILED")
        send_message("Couldn't fetch that voice message — please try again.", cid, thread_id)
        return None
    fmt = _audio_format(msg, obj)
    _log(f"voice: downloaded {len(audio)} bytes, fmt={fmt}; transcribing…")
    text = _transcribe.transcribe(audio, fmt)
    if not text:
        _log("voice: transcription returned empty/None")
        if not _config.get_secret("OPENROUTER_API_KEY"):
            send_message("Voice isn't set up yet — add OPENROUTER_API_KEY to secrets.env to "
                         "enable transcription. You can still type to me.", cid, thread_id)
        else:
            send_message("Sorry, I couldn't transcribe that — try again, or type it.", cid, thread_id)
        return None
    _log(f"voice: transcript ok ({len(text)} chars): {text[:60]!r}")
    send_message(f"🎙️ {text}", cid, thread_id)  # echo so you can see/correct what was heard
    return text


def get_owner_chat_id():
    return _config.runtime("telegram_chat_id")


def _load_offset() -> int:
    p = _paths.telegram_offset_file()
    if p.exists():
        try:
            return int(p.read_text().strip() or "0")
        except ValueError:
            return 0
    return 0


def _save_offset(offset: int) -> None:
    try:
        p = _paths.telegram_offset_file()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(str(offset))
    except OSError:
        pass


def _get_updates(token: str, offset: int, timeout: int):
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    r = requests.get(url, params={"offset": offset, "timeout": timeout}, timeout=timeout + 15)
    r.raise_for_status()
    return r.json().get("result", [])


def _handle_text(text: str, cid, conversation_id: str, thread_id=None) -> None:
    def reply(t):
        send_message(t, cid, thread_id)

    low = text.strip().lower()
    if low in ("/start", "/help"):
        reply(HELP)
        return
    if low == "/whoami":
        msg = f"This chat id is: {cid}"
        if thread_id:
            msg += f"\nThis topic's thread id is: {thread_id}"
        reply(msg)
        return
    if low == "/clear":
        n = _sessions.clear(conversation_id)
        reply(f"🧹 Cleared this thread's short-term context ({n} turn(s)). "
              f"Your long-term memory is untouched — I can still recall anything later.")
        return
    if low.startswith("/feedback"):
        parts = text.strip().split(None, 2)
        if len(parts) < 3:
            reply("usage: /feedback <useful|noise> <item>")
        else:
            try:
                _feedback.record_feedback(parts[2], parts[1])
                reply(f"Recorded as {parts[1].lower()}. Thanks — it tunes your digest.")
            except ValueError:
                reply("verdict must be 'useful' or 'noise'.")
        return
    if low == "/reminders":
        reply("⏰ Upcoming reminders:\n" + (_reminders.format_upcoming(20) or "(none)"))
        return
    if low == "/learned":
        pend = _learned.pending()
        if not pend:
            reply("Nothing pending to confirm right now. ✅")
        else:
            lines = ["📥 Learned, pending your confirmation —", "reply /keep <id…> or /drop <id…>:"]
            for it in pend:
                tag = it.get("polarity") or it.get("rule_kind") or it["type"]
                lines.append(f"  [{it['id']}] {it['type']}/{tag}: {it['text']}")
            reply("\n".join(lines))
        return
    if low.startswith("/keep"):
        kept = [d["text"] for d in (_learned.promote(i) for i in text.split()[1:]) if d]
        reply(("✅ Saved to your files: " + "; ".join(kept)) if kept
              else "No matching pending items for those ids.")
        return
    if low.startswith("/drop"):
        dropped = [d["text"] for d in (_learned.drop(i) for i in text.split()[1:]) if d]
        reply(("🗑 Dropped: " + "; ".join(dropped)) if dropped
              else "No matching items for those ids.")
        return

    send_typing(cid, thread_id)
    res = _assistant.respond(text, conversation_id=conversation_id)
    out = res["answer"]
    cites = res.get("citations") or []
    # Only show the provenance line when memory was genuinely relevant (strong match) —
    # otherwise it's noise (e.g. citing unrelated notes for a general question). The model
    # still cites specific facts inline when it uses them.
    if cites and not res.get("engine_error") and res.get("confidence") == "strong":
        out += "\n\n— sources: " + " ".join(f"[{c['source_id']}]" for c in cites[:5])
    reply(out)


def run() -> None:
    token = _token()
    if not token:
        print("No TELEGRAM_BOT_TOKEN in config/secrets.env — Telegram bot disabled.", file=sys.stderr)
        raise SystemExit(1)
    tg = _config.load_config().get("telegram", {})
    if not tg.get("enabled", True):
        print("telegram.enabled is false in config — not starting.", file=sys.stderr)
        raise SystemExit(0)
    poll = int(tg.get("poll_timeout", 50))
    expected = tg.get("expected_chat_id")

    offset = _load_offset()
    _log(f"polling (owner={get_owner_chat_id()}). Ctrl-C to stop.")
    backoff = 1
    while True:
        _config.reload()  # pick up config/secrets edits (new keys, owner, model) without a restart
        try:
            updates = _get_updates(token, offset, poll)
            backoff = 1
        except requests.RequestException as exc:
            _log(f"poll error ({type(exc).__name__}); retrying in {backoff}s")
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)
            continue
        except KeyboardInterrupt:
            _log("stopped.")
            break

        for upd in updates:
            offset = upd["update_id"] + 1
            _save_offset(offset)
            msg = upd.get("message") or upd.get("edited_message")
            if not msg:
                continue
            cid = msg["chat"]["id"]
            thread_id = msg.get("message_thread_id")  # forum topic, if any
            conversation_id = f"telegram:{cid}" + (f":{thread_id}" if thread_id else "")
            owner = get_owner_chat_id()
            if owner is None:
                if expected is not None and cid != expected:
                    continue  # someone other than the pinned owner — ignore silently
                _config.set_runtime("telegram_chat_id", cid)
                owner = cid
                send_message(
                    "👋 personal-os is now linked to this chat (only this chat is "
                    "authorized). Forum topics work — each topic is its own thread with "
                    "its own short-term context. Send me text or a voice note, or /help.",
                    cid, thread_id,
                )
            if cid != owner:
                continue  # drop non-owner BEFORE the engine is touched (no log of body)
            _mtype = ("voice" if "voice" in msg else "audio" if "audio" in msg
                      else "text" if msg.get("text") else "other")
            _log(f"msg from chat={cid} thread={thread_id} type={_mtype}")
            try:
                text = msg.get("text")
                if not text and ("voice" in msg or "audio" in msg):
                    text = _voice_to_text(token, msg, cid, thread_id)
                if not text:
                    continue  # unsupported message type, or transcription failed (already replied)
                _handle_text(text, cid, conversation_id, thread_id)
            except Exception as exc:  # never crash the loop on one bad message
                _log(f"handler error: {type(exc).__name__}")
                send_message("Sorry — something went wrong handling that. Try again.", cid, thread_id)


if __name__ == "__main__":
    run()
