"""RECALL: find by meaning, with sources, and admit gaps (the third job of memory).

Multi-tier:
  tier 0 — the injected identity snapshot is ALWAYS in the system prompt (assistant.py),
           so the model consults it first for free.
  tier 1 — hybrid index search (semantic + keyword, RRF-fused) over everything stored.

recall() returns the retrieved hits + a CONFIDENCE signal and a `found` flag. Honesty
is prompt+retrieval driven (D16/ADR-10): the confidence is a soft signal fed to the
model, and the system prompt forbids inventing personal facts — so a weak/irrelevant
match leads the model to say "I don't have that", never to fabricate. `found` is True
only on a strong semantic match OR a meaningful (non-stopword) keyword match, so common
stopwords ("my", "name") don't create false positives.
"""
from __future__ import annotations

import re

from . import config as _config
from . import index as _index

STOPWORDS = {
    "the", "and", "for", "are", "was", "were", "you", "your", "yours", "what", "whats",
    "who", "whom", "whose", "when", "where", "why", "how", "did", "does", "do", "is",
    "am", "be", "been", "being", "my", "mine", "me", "i", "we", "us", "our", "ours",
    "a", "an", "of", "to", "in", "on", "at", "it", "its", "this", "that", "these",
    "those", "with", "about", "have", "has", "had", "name", "names", "tell", "say",
    "said", "give", "get", "got", "can", "could", "would", "should", "any", "some",
}


def _meaningful_tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"\w+", text.lower()) if len(t) >= 3 and t not in STOPWORDS}


def recall(query: str, *, k: int | None = None) -> dict:
    cfg = _config.load_config().get("recall", {})
    k = int(cfg.get("k", 6)) if k is None else k
    weak = float(cfg.get("weak_sim", 0.35))

    hits = _index.search(query, k=k)
    if not hits:
        return {"query": query, "found": False, "confidence": "none",
                "hits": [], "citations": [], "top_sim": 0.0}

    top_sim = max(h.get("vec_sim", 0.0) for h in hits)
    qtokens = _meaningful_tokens(query)
    kw_meaningful = any(
        h.get("kw") and (qtokens & _meaningful_tokens(h["text"])) for h in hits
    )
    strong = top_sim >= weak
    found = strong or kw_meaningful
    confidence = "strong" if strong else ("weak" if found else "none")

    citations = [
        {"source_id": h["source_id"], "source_path": h["source_path"], "kind": h["kind"]}
        for h in hits
    ]
    return {"query": query, "found": found, "confidence": confidence,
            "hits": hits, "citations": citations, "top_sim": round(top_sim, 4)}


def format_memory_block(rec: dict) -> str:
    """Render retrieved memory as DATA for the engine. On 'none' confidence we send an
    explicit no-match note (so the model admits the gap rather than guessing)."""
    if not rec["hits"] or rec["confidence"] == "none":
        return "(No relevant past context found for this message.)"
    lines = ["Relevant context from earlier conversations (use silently — never cite, list, "
             "or mention files/sources):"]
    for h in rec["hits"]:
        lines.append(f"- {h['text'].strip()}")
    if rec["confidence"] != "strong":
        lines.append("(These are loose matches — use only if clearly relevant; otherwise "
                     "just say you don't have it.)")
    return "\n".join(lines)


if __name__ == "__main__":
    import json
    import sys

    q = " ".join(sys.argv[1:]) or "test"
    r = recall(q)
    print(json.dumps({k: v for k, v in r.items() if k != "hits"}, indent=2))
    for h in r["hits"]:
        print(f"  [{h['vec_sim']:.2f} kw={h['kw']}] ({h['source_id']}) {h['text'][:90]!r}")
