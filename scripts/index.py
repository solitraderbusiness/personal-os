"""Local hybrid vector + keyword index (principles 3 & 4).

ONE portable sqlite file holds everything:
  - chunks       : text + citation metadata (the canonical recall source; always populated)
  - vec_chunks   : sqlite-vec vec0 virtual table (semantic search; created only if the
                   sqlite-vec extension loads — otherwise the index runs FTS5-only)
  - fts_chunks   : FTS5 virtual table (keyword search)
  - meta         : embedder backend NAME + dim (so a model/dim swap is DETECTED and the
                   index degrades to keyword-only rather than silently mixing vectors)

search() fuses vector + keyword with Reciprocal Rank Fusion (RRF). A no-op reranker
SEAM (`rerank`) is left for a future second pass (out of scope v1).

Robustness (folded in from the design review):
  - sqlite-vec import/load is GUARDED; missing => FTS5-only, never an import crash.
  - dim/backend mismatch => FTS5-only + a 'rebuild required' signal, never a raise
    inside search/recall/capture (would crash the per-message loop).
  - all writes take a process-level flock; reindex --reset deletes under that lock
    (safe: a concurrent reader keeps its old inode on Linux; a fresh db is created).

Citations: each chunk carries a human-readable `source_id` (e.g. "daily/2026-06-16#003",
"authored/about-me.md") so recall can always point to exactly where a fact came from.
"""
from __future__ import annotations

import contextlib
import fcntl
import hashlib
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from . import config as _config
from . import embeddings as _emb
from . import paths as _paths

AUTHORED, DAILY, DIGEST, CONVERSATION = "authored", "daily", "digest", "conversation"

# Daily-log entry marker (frozen cross-module contract D17g). capture WRITES it,
# index + snapshot READ it. source_id is reused verbatim from the marker.
DAILY_MARKER_RE = re.compile(r"<!--\s*turn\s+source_id=(?P<sid>\S+).*?-->")

_VEC_AVAILABLE: bool | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _vec_available() -> bool:
    global _VEC_AVAILABLE
    if _VEC_AVAILABLE is None:
        try:
            import sqlite_vec  # noqa: F401
            _VEC_AVAILABLE = True
        except Exception:
            _VEC_AVAILABLE = False
    return _VEC_AVAILABLE


@contextlib.contextmanager
def _write_lock():
    _paths.index_dir().mkdir(parents=True, exist_ok=True)
    f = open(_paths.index_lock(), "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(f, fcntl.LOCK_UN)
        f.close()


def _connect() -> tuple[sqlite3.Connection, bool]:
    """Open the index db. Returns (conn, vec_ok) where vec_ok means the sqlite-vec
    extension loaded for this connection."""
    _paths.index_dir().mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_paths.index_db()), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    vec_ok = False
    if _vec_available():
        try:
            import sqlite_vec
            conn.enable_load_extension(True)
            sqlite_vec.load(conn)
            conn.enable_load_extension(False)
            vec_ok = True
        except Exception:
            vec_ok = False
    return conn, vec_ok


def _apply_schema(conn: sqlite3.Connection, vec_ok: bool, dim: int) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS chunks (
               id INTEGER PRIMARY KEY,
               chunk_key TEXT UNIQUE,
               source_path TEXT,
               source_id TEXT,
               kind TEXT,
               text TEXT,
               content_hash TEXT,
               generated_at TEXT
           )"""
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_src ON chunks(source_path)")
    conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS fts_chunks USING fts5(text)")
    if vec_ok:
        conn.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING vec0(embedding float[{dim}])"
        )
    # seed meta if fresh
    if conn.execute("SELECT 1 FROM meta WHERE key='dim'").fetchone() is None:
        conn.execute("INSERT INTO meta(key,value) VALUES('dim',?)", (str(dim),))
    if conn.execute("SELECT 1 FROM meta WHERE key='backend'").fetchone() is None:
        conn.execute("INSERT INTO meta(key,value) VALUES('backend',?)", (_emb.backend(),))


def init_index() -> None:
    """Create the schema if absent (idempotent). Succeeds in FTS5-only mode too."""
    dim = _emb.dim()
    conn, vec_ok = _connect()
    try:
        _apply_schema(conn, vec_ok, dim)
        conn.commit()
    finally:
        conn.close()


def _vectors_usable(conn: sqlite3.Connection, vec_ok: bool) -> bool:
    """True iff vector search is safe: extension loaded AND stored backend+dim match
    the live embedder. On mismatch we degrade to FTS5-only (never raise) — D17e."""
    if not vec_ok:
        return False
    try:
        rd = conn.execute("SELECT value FROM meta WHERE key='dim'").fetchone()
        rb = conn.execute("SELECT value FROM meta WHERE key='backend'").fetchone()
    except sqlite3.Error:
        return False
    if rd is None:
        return True  # fresh; will be seeded on first write
    if int(rd["value"]) != _emb.dim():
        return False
    if rb is not None and rb["value"] != _emb.backend():
        return False
    return True


# --------------------------------------------------------------------------- #
# Chunking
# --------------------------------------------------------------------------- #
def _strip_frontmatter(text: str) -> str:
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            return text[end + 4 :].lstrip("\n")
    return text


def _strip_html_comments(text: str) -> str:
    return re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)


def _pack_paragraphs(text: str, target: int = 700) -> list[str]:
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    out, buf = [], ""
    for p in paras:
        if buf and len(buf) + len(p) + 2 > target:
            out.append(buf.strip())
            buf = p
        else:
            buf = f"{buf}\n\n{p}" if buf else p
    if buf.strip():
        out.append(buf.strip())
    return out


def _units_authored(path: Path, text: str) -> list[tuple[str, str]]:
    body = _strip_html_comments(_strip_frontmatter(text))
    parts = _pack_paragraphs(body)
    if len(parts) <= 1:
        return [(f"authored/{path.name}", parts[0])] if parts else []
    return [(f"authored/{path.name} #{i+1}", part) for i, part in enumerate(parts)]


def _units_daily(path: Path, text: str) -> list[tuple[str, str]]:
    """Split on the frozen turn marker; reuse each entry's source_id verbatim."""
    body = _strip_frontmatter(text)
    matches = list(DAILY_MARKER_RE.finditer(body))
    if not matches:
        b = body.strip()
        return [(f"daily/{path.stem}", b)] if b else []
    units: list[tuple[str, str]] = []
    for i, m in enumerate(matches):
        sid = m.group("sid")
        seg = body[m.end() : (matches[i + 1].start() if i + 1 < len(matches) else len(body))].strip()
        if seg:
            units.append((sid, seg))
    return units


def _units_digest(path: Path, text: str) -> list[tuple[str, str]]:
    body = _strip_frontmatter(text).strip()
    return [(f"digest/{path.stem}", body)] if body else []


def _units_conversation(path: Path, text: str) -> list[tuple[str, str]]:
    return [(f"conversation/{path.stem} #{i+1}", p) for i, p in enumerate(_pack_paragraphs(text))]


_EXTRACTORS = {
    AUTHORED: _units_authored,
    DAILY: _units_daily,
    DIGEST: _units_digest,
    CONVERSATION: _units_conversation,
}


# --------------------------------------------------------------------------- #
# Indexing (delete-then-insert per source = idempotent; flock-guarded)
# --------------------------------------------------------------------------- #
def index_units(source_path: str, kind: str, units: list[tuple[str, str]]) -> int:
    """Replace all indexed rows for `source_path` with `units` [(source_id, text)]."""
    init_index()
    units = [(sid, txt) for sid, txt in units if txt and txt.strip()]
    with _write_lock():
        conn, vec_ok = _connect()
        try:
            vu = _vectors_usable(conn, vec_ok)
            old = [r["id"] for r in conn.execute(
                "SELECT id FROM chunks WHERE source_path=?", (source_path,)
            )]
            for rid in old:
                if vec_ok:
                    conn.execute("DELETE FROM vec_chunks WHERE rowid=?", (rid,))
                conn.execute("DELETE FROM fts_chunks WHERE rowid=?", (rid,))
            conn.execute("DELETE FROM chunks WHERE source_path=?", (source_path,))

            if not units:
                conn.commit()
                return 0

            vectors = _emb.embed([t for _, t in units]) if vu else None
            if vu:
                from sqlite_vec import serialize_float32
            now = _now_iso()
            for i, (sid, txt) in enumerate(units):
                chash = hashlib.md5(txt.encode("utf-8")).hexdigest()
                cur = conn.execute(
                    """INSERT INTO chunks
                       (chunk_key, source_path, source_id, kind, text, content_hash, generated_at)
                       VALUES (?,?,?,?,?,?,?)""",
                    (f"{source_path}#{i}", source_path, sid, kind, txt, chash, now),
                )
                rid = cur.lastrowid
                conn.execute("INSERT INTO fts_chunks(rowid, text) VALUES (?, ?)", (rid, txt))
                if vu:
                    conn.execute(
                        "INSERT INTO vec_chunks(rowid, embedding) VALUES (?, ?)",
                        (rid, serialize_float32(vectors[i].tolist())),
                    )
            conn.commit()
            return len(units)
        finally:
            conn.close()


def index_file(path: Path, kind: str) -> int:
    path = Path(path)
    if not path.exists():
        return 0
    text = path.read_text(encoding="utf-8", errors="replace")
    return index_units(_paths.rel_to_data(path), kind, _EXTRACTORS[kind](path, text))


def _index_all_sources() -> dict:
    counts = {AUTHORED: 0, DAILY: 0, DIGEST: 0, CONVERSATION: 0}
    for name in _paths.AUTHORED_FILES:
        counts[AUTHORED] += index_file(_paths.authored_file(name), AUTHORED)
    for f in sorted(_paths.daily_dir().glob("*.md")):
        counts[DAILY] += index_file(f, DAILY)
    for f in sorted(_paths.digests_dir().glob("*.md")):
        counts[DIGEST] += index_file(f, DIGEST)
    if _config.load_config().get("index", {}).get("conversations") and _paths.conversations_dir().exists():
        for f in sorted(_paths.conversations_dir().glob("*.md")):
            counts[CONVERSATION] += index_file(f, CONVERSATION)
    return counts


def reindex_all(reset: bool = False) -> dict:
    """(Re)index every source. reset=True drops the db first (use after a model/dim
    change). The drop happens under the write lock; a concurrent reader keeps its old
    inode (Linux) and a fresh db is created — no corruption."""
    if reset:
        with _write_lock():
            for suffix in ("", "-wal", "-shm"):
                p = Path(str(_paths.index_db()) + suffix)
                if p.exists():
                    p.unlink()
    init_index()
    return _index_all_sources()


# --------------------------------------------------------------------------- #
# Search (hybrid vector + keyword via RRF; FTS5-only when vectors unavailable)
# --------------------------------------------------------------------------- #
def _fts_query(query: str) -> str:
    toks = [t for t in re.findall(r"\w+", query.lower()) if len(t) > 1][:24]
    return " OR ".join(f'"{t}"' for t in toks)


def rerank(query: str, hits: list[dict]) -> list[dict]:
    """SEAM for a future reranker (cross-encoder / LLM reorder). v1 = identity.
    TODO(v2): re-score `hits` against `query` and reorder. Out of scope for v1."""
    return hits


def search(query: str, k: int | None = None, candidate_k: int | None = None) -> list[dict]:
    """Return up to k fused hits (dicts: source_id/source_path/kind/text/score/vec_sim/kw).
    Degrades to keyword-only when vectors are unavailable. Empty list if no rows."""
    cfg = _config.load_config().get("recall", {})
    k = int(cfg.get("k", 6)) if k is None else k
    candidate_k = int(cfg.get("candidate_k", 24)) if candidate_k is None else candidate_k
    rrf_k = int(cfg.get("rrf_k", 60))

    if not _paths.index_db().exists():
        return []
    conn, vec_ok = _connect()
    try:
        if conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='chunks'"
        ).fetchone() is None:
            return []
        if conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == 0:
            return []
        vu = _vectors_usable(conn, vec_ok)

        vec_order: list[int] = []
        sim_by_id: dict[int, float] = {}
        if vu:
            from sqlite_vec import serialize_float32
            qvec = _emb.embed_one(query)
            for r in conn.execute(
                "SELECT rowid, distance FROM vec_chunks "
                "WHERE embedding MATCH ? ORDER BY distance LIMIT ?",
                (serialize_float32(qvec.tolist()), candidate_k),
            ):
                vec_order.append(r["rowid"])
                sim_by_id[r["rowid"]] = max(0.0, 1.0 - (r["distance"] ** 2) / 2.0)

        fts_order: list[int] = []
        fq = _fts_query(query)
        if fq:
            try:
                fts_order = [
                    r["rowid"]
                    for r in conn.execute(
                        "SELECT rowid FROM fts_chunks WHERE fts_chunks MATCH ? "
                        "ORDER BY rank LIMIT ?",
                        (fq, candidate_k),
                    )
                ]
            except sqlite3.OperationalError:
                fts_order = []

        scores: dict[int, float] = {}
        for rank, rid in enumerate(vec_order):
            scores[rid] = scores.get(rid, 0.0) + 1.0 / (rrf_k + rank + 1)
        for rank, rid in enumerate(fts_order):
            scores[rid] = scores.get(rid, 0.0) + 1.0 / (rrf_k + rank + 1)
        if not scores:
            return []

        kw_ids = set(fts_order)
        top_ids = sorted(scores, key=lambda i: scores[i], reverse=True)[: max(k, candidate_k)]
        placeholders = ",".join("?" * len(top_ids))
        rows = {
            r["id"]: r
            for r in conn.execute(
                f"SELECT id, source_path, source_id, kind, text, generated_at "
                f"FROM chunks WHERE id IN ({placeholders})",
                top_ids,
            )
        }
        hits = []
        for rid in top_ids:
            r = rows.get(rid)
            if not r:
                continue
            hits.append({
                "source_id": r["source_id"],
                "source_path": r["source_path"],
                "kind": r["kind"],
                "text": r["text"],
                "generated_at": r["generated_at"],
                "score": round(scores[rid], 6),
                "vec_sim": round(sim_by_id.get(rid, 0.0), 4),
                "kw": rid in kw_ids,
            })
        return rerank(query, hits)[:k]
    finally:
        conn.close()


def stats() -> dict:
    if not _paths.index_db().exists():
        return {"chunks": 0, "backend": _emb.backend(), "dim": _emb.dim(),
                "exists": False, "vectors": False}
    conn, vec_ok = _connect()
    try:
        if conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='chunks'"
        ).fetchone() is None:
            return {"chunks": 0, "exists": True, "vectors": False}
        n = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        by_kind = {r["kind"]: r["c"] for r in conn.execute(
            "SELECT kind, COUNT(*) c FROM chunks GROUP BY kind")}
        vu = _vectors_usable(conn, vec_ok)
        out = {
            "chunks": n, "by_kind": by_kind, "backend": _emb.backend(), "dim": _emb.dim(),
            "exists": True, "vectors": vu, "db": str(_paths.index_db()),
        }
        if vec_ok and not vu:
            out["rebuild_required"] = (
                "embedder changed since last index; run: python -m scripts.index reindex --reset"
            )
        return out
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# CLI: python -m scripts.index <reindex [--reset] | stats | search "query">
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    import json
    import sys

    args = sys.argv[1:]
    cmd = args[0] if args else "stats"
    if cmd == "reindex":
        print(json.dumps(reindex_all(reset=("--reset" in args)), indent=2))
    elif cmd == "search":
        q = " ".join(a for a in args[1:] if not a.startswith("--"))
        for h in search(q):
            kw = "+kw" if h["kw"] else "   "
            print(f"[{h['score']:.4f} sim={h['vec_sim']:.2f} {kw}] ({h['source_id']}) {h['text'][:110]!r}")
    else:
        print(json.dumps(stats(), indent=2))
