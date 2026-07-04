"""
api/services/search.py — semantic / keyword / hybrid search (ports search.py).

Modes:
  * ``semantic`` — pgvector cosine (``embedding <=> qv``) over segment embeddings.
  * ``keyword``  — Postgres full-text search over the generated ``fts`` tsvector.
  * ``hybrid``   — Reciprocal Rank Fusion (RRF) of the two ranked lists.

To keep the API image ML-free, the query is **not** embedded in-process. It is
fetched from an OpenAI-compatible embeddings endpoint (``EMBEDDINGS_URL``, e.g. a
CPU TEI or vLLM container serving the same BGE-M3 model the worker uses, so the
query vector lands in the same space). If that endpoint is not configured or is
unreachable, semantic/hybrid gracefully degrade to keyword search.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from api.settings import get_api_settings

RRF_K = 60  # standard Reciprocal Rank Fusion constant

_embed_client = None


def _embed_query(q: str) -> list[float] | None:
    """Return a normalized query embedding via the OpenAI-compatible endpoint, or
    None if embeddings are unavailable (caller falls back to keyword)."""
    global _embed_client
    s = get_api_settings()
    url = getattr(s, "embeddings_url", None)
    if not url:
        return None
    try:
        if _embed_client is None:
            from openai import OpenAI

            _embed_client = OpenAI(
                base_url=url,
                api_key=getattr(s, "embeddings_api_key", "EMPTY") or "EMPTY",
                timeout=15,
            )
        resp = _embed_client.embeddings.create(model=s.embeddings_model, input=[q])
        return list(resp.data[0].embedding)
    except Exception:
        return None


def _vec_literal(vec: list[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in vec) + "]"


def _row_to_hit(r) -> dict:
    return {
        "video_id": r.video_id,
        "seg_index": r.seg_index,
        "start_sec": float(r.start_sec),
        "end_sec": float(r.end_sec),
        "topic": r.topic,
        "subject": r.subject,
        "grade_level": r.grade_level,
        "summary": r.summary,
        "score": float(r.score) if r.score is not None else 0.0,
    }


def _semantic_rows(session: Session, qv: list[float], limit: int) -> list:
    s = get_api_settings()
    # tune recall for this query (HNSW ef_search); scoped to the transaction
    session.execute(text("SET LOCAL hnsw.ef_search = :ef"), {"ef": s.hnsw_ef_search})
    stmt = text("""
        SELECT s.video_id, s.seg_index, s.start_sec, s.end_sec, s.topic, s.subject,
               s.grade_level, s.summary, 1 - (s.embedding <=> CAST(:qv AS vector)) AS score
        FROM segments s
        JOIN videos v ON v.video_id = s.video_id
        WHERE v.status <> 'soft_deleted' AND s.embedding IS NOT NULL
        ORDER BY s.embedding <=> CAST(:qv AS vector)
        LIMIT :k""")
    return list(session.execute(stmt, {"qv": _vec_literal(qv), "k": limit}).fetchall())


def _keyword_rows(session: Session, q: str, limit: int) -> list:
    stmt = text("""
        SELECT s.video_id, s.seg_index, s.start_sec, s.end_sec, s.topic, s.subject,
               s.grade_level, s.summary,
               ts_rank(s.fts, plainto_tsquery('simple', :q)) AS score
        FROM segments s
        JOIN videos v ON v.video_id = s.video_id
        WHERE v.status <> 'soft_deleted' AND s.fts @@ plainto_tsquery('simple', :q)
        ORDER BY score DESC
        LIMIT :k""")
    return list(session.execute(stmt, {"q": q, "k": limit}).fetchall())


def semantic_search(session: Session, q: str, limit: int) -> tuple[str, list[dict]]:
    qv = _embed_query(q)
    if qv is None:
        return "keyword", [_row_to_hit(r) for r in _keyword_rows(session, q, limit)]
    return "semantic", [_row_to_hit(r) for r in _semantic_rows(session, qv, limit)]


def keyword_search(session: Session, q: str, limit: int) -> tuple[str, list[dict]]:
    return "keyword", [_row_to_hit(r) for r in _keyword_rows(session, q, limit)]


def hybrid_search(session: Session, q: str, limit: int) -> tuple[str, list[dict]]:
    """RRF over the semantic and keyword rankings. Falls back to keyword-only when
    embeddings are unavailable."""
    qv = _embed_query(q)
    pool = max(limit * 4, 40)
    kw = _keyword_rows(session, q, pool)
    if qv is None:
        return "keyword", [_row_to_hit(r) for r in kw[:limit]]
    sem = _semantic_rows(session, qv, pool)

    fused: dict[tuple, dict] = {}

    def fuse(rows: list, weight_key: str) -> None:
        for rank, r in enumerate(rows):
            key = (r.video_id, r.seg_index)
            entry = fused.setdefault(key, {"row": r, "rrf": 0.0})
            entry["rrf"] += 1.0 / (RRF_K + rank + 1)

    fuse(sem, "sem")
    fuse(kw, "kw")
    ordered = sorted(fused.values(), key=lambda e: e["rrf"], reverse=True)[:limit]
    results = []
    for e in ordered:
        hit = _row_to_hit(e["row"])
        hit["score"] = round(e["rrf"], 6)  # RRF fused score
        results.append(hit)
    return "hybrid", results


def search(session: Session, q: str, mode: str, limit: int) -> tuple[str, list[dict]]:
    if mode == "keyword":
        return keyword_search(session, q, limit)
    if mode == "hybrid":
        return hybrid_search(session, q, limit)
    return semantic_search(session, q, limit)
