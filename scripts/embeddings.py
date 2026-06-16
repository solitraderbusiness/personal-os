"""Local, owned, swappable embeddings (principles 3 & 4).

Backend = model2vec static embeddings (no torch, CPU, zero API cost). If the model
can't be loaded (not downloaded / offline), a DETERMINISTIC hashing embedder takes
over so the system never hard-fails and tests run without network. Vectors are
L2-normalized so L2 distance ranks like cosine similarity.
"""
from __future__ import annotations

import hashlib
import os

# Quiet the HF hub download progress bars so the CLI/bot/cron output stays clean.
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

import numpy as np

from . import config as _config

_MODEL = None
_BACKEND: str | None = None  # "model2vec" | "hash"
_DIM: int | None = None


def _load() -> None:
    global _MODEL, _BACKEND
    if _BACKEND is not None:
        return
    name = (_config.load_config().get("embedding", {}) or {}).get("model", "")
    if name:
        try:
            from model2vec import StaticModel

            _MODEL = StaticModel.from_pretrained(name)
            _BACKEND = "model2vec"
            return
        except Exception:
            _MODEL = None
    _BACKEND = "hash"


def backend() -> str:
    _load()
    return _BACKEND  # type: ignore[return-value]


def dim() -> int:
    """The real embedding dimension of the active backend (probed once)."""
    global _DIM
    if _DIM is not None:
        return _DIM
    _load()
    if _BACKEND == "model2vec":
        try:
            _DIM = int(np.asarray(_MODEL.encode(["x"])).reshape(1, -1).shape[1])
            return _DIM
        except Exception:
            pass
    _DIM = int((_config.load_config().get("embedding", {}) or {}).get("dim", 256))
    return _DIM


def _normalize(arr: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (arr / norms).astype(np.float32)


def _hash_embed(text: str, d: int) -> np.ndarray:
    v = np.zeros(d, dtype=np.float32)
    for tok in text.lower().split():
        h = int(hashlib.md5(tok.encode("utf-8")).hexdigest(), 16)
        v[h % d] += 1.0 if (h // d) % 2 == 0 else -1.0
    return v


def embed(texts: list[str]) -> np.ndarray:
    """Return an (n, dim) float32 array of L2-normalized embeddings."""
    _load()
    d = dim()
    if not texts:
        return np.zeros((0, d), dtype=np.float32)
    if _BACKEND == "model2vec":
        arr = np.asarray(_MODEL.encode(list(texts)), dtype=np.float32).reshape(len(texts), -1)
        return _normalize(arr)
    return _normalize(np.vstack([_hash_embed(t, d) for t in texts]))


def embed_one(text: str) -> np.ndarray:
    return embed([text])[0]
