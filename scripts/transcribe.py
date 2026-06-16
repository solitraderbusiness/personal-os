"""Voice transcription via OpenRouter's dedicated transcription endpoint.

Telegram voice notes are OGG/Opus, which OpenRouter accepts directly (no ffmpeg /
conversion). One OPENROUTER_API_KEY lets you pick any STT model via config.voice.model
(default openai/whisper-large-v3 — strong Farsi, fast). Sending audio to an STT model is
the same category as the text already going to the answer model ("only model calls leave").

transcribe() is best-effort: returns None on any failure (missing key, network, API error)
so the bot can fall back to a friendly "couldn't transcribe" rather than crashing. The API
key is never logged.
"""
from __future__ import annotations

import base64

import requests

from . import config as _config

ENDPOINT = "https://openrouter.ai/api/v1/audio/transcriptions"


def enabled() -> bool:
    return bool(_config.load_config().get("voice", {}).get("enabled", True))


def transcribe(audio_bytes: bytes, fmt: str = "ogg", *, language: str | None = None) -> str | None:
    """Return the transcribed text, or None if transcription is unavailable/failed."""
    if not enabled() or not audio_bytes:
        return None
    key = _config.get_secret("OPENROUTER_API_KEY")
    if not key:
        return None  # not configured — caller explains how to enable
    cfg = _config.load_config().get("voice", {})
    model = str(cfg.get("model") or "openai/whisper-large-v3")
    lang = language if language is not None else (cfg.get("language") or None)

    body = {
        "input_audio": {"data": base64.b64encode(audio_bytes).decode("ascii"), "format": fmt},
        "model": model,
    }
    if lang:
        body["language"] = lang
    try:
        r = requests.post(
            ENDPOINT,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=body,
            timeout=120,
        )
        if r.status_code != 200:
            return None
        text = (r.json().get("text") or "").strip()
        return text or None
    except (requests.RequestException, ValueError):
        return None
