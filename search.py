"""
search.py — query processed videos straight from cloud Postgres (no Kaggle, no GPU).

Semantic search (pgvector) is used automatically when sentence-transformers is
installed (CPU is fine); otherwise it falls back to Postgres full-text search,
which needs only SQLAlchemy. Results carry topic/subject and the voiced/silent
flag so you can tell narrated segments from silent-animation ones.

USAGE (from  D:\\Katbook_VIP_2 ):
    python search.py "time period of a pendulum"
    python search.py "rational numbers" --subject Mathematics --k 5
    python search.py "atom bonding" --silent          # only silent-video segments
    python search.py "oscillation" --mode fts          # force keyword-only (no ML deps)

DB URL comes from env DATABASE_URL or db_url.txt (same as sync_results.py).
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def get_db_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url and (HERE / "db_url.txt").exists():
        url = (HERE / "db_url.txt").read_text(encoding="utf-8").strip()
    if not url:
        sys.exit("No DATABASE_URL (env var or db_url.txt).")
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg2://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return url


def embed(query: str):
    """Normalized embedding for semantic search, or None if deps are missing."""
    try:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", device="cpu")
        return model.encode([query], normalize_embeddings=True)[0].tolist()
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("--mode", choices=["auto", "semantic", "fts"], default="auto")
    ap.add_argument("--subject"); ap.add_argument("--grade"); ap.add_argument("--ctype")
    ap.add_argument("--silent", action="store_true", help="only silent-video segments")
    ap.add_argument("--voice", action="store_true", help="only narrated-video segments")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--min-score", type=float, default=None,
                    help="hide results weaker than this (default 0.30 for semantic; "
                         "pass 0 to show everything)")
    args = ap.parse_args()

    from sqlalchemy import create_engine, text as sql
    eng = create_engine(get_db_url(), pool_pre_ping=True)

    # Filters live on segments.llm (JSONB) and the videos.has_speech flag (join).
    filt, params = [], {"q": args.query, "k": args.k}
    join = ""
    if args.subject: filt.append("s.llm->>'subject' = :subject"); params["subject"] = args.subject
    if args.grade:   filt.append("s.llm->>'grade_level' = :grade"); params["grade"] = args.grade
    if args.ctype:   filt.append("s.llm->>'content_type' = :ctype"); params["ctype"] = args.ctype
    if args.silent or args.voice:
        join = "JOIN videos v ON v.video_id = s.video_id"
        filt.append("v.has_speech = :hs"); params["hs"] = bool(args.voice)
    where = (" AND " + " AND ".join(filt)) if filt else ""

    qv = embed(args.query) if args.mode in ("auto", "semantic") else None
    if qv is not None:
        params["qv"] = str(qv)
        stmt = sql(f"""SELECT s.video_id, s.seg_index, s.start_sec, s.end_sec,
            s.llm->>'topic' AS topic, s.llm->>'subject' AS subject,
            1 - (s.embedding <=> :qv) AS score
            FROM segments s {join} WHERE TRUE {where}
            ORDER BY s.embedding <=> :qv LIMIT :k""")
        mode = "semantic (pgvector)"
    else:
        stmt = sql(f"""SELECT s.video_id, s.seg_index, s.start_sec, s.end_sec,
            s.llm->>'topic' AS topic, s.llm->>'subject' AS subject,
            ts_rank(s.fts, plainto_tsquery('english', :q)) AS score
            FROM segments s {join}
            WHERE s.fts @@ plainto_tsquery('english', :q) {where}
            ORDER BY score DESC LIMIT :k""")
        mode = "full-text (tsvector)"

    with eng.connect() as cx:
        rows = cx.execute(stmt, params).fetchall()

    # Production relevance gate: pgvector/FTS always return the top-k NEAREST rows,
    # even when nothing is truly relevant. We keep "real hits only", not
    # "least-far filler", using a gate that adapts to the query:
    #   floor = max(ABS_FLOOR, top_score * REL_RATIO)
    # ABS_FLOOR drops the "nothing relevant" case (e.g. 'history of ancient rome'
    # when the library has none); REL_RATIO keeps results close to the BEST match,
    # so exact-word queries (top ~0.44) and paraphrases (top ~0.21) both cut their
    # own filler correctly — a single fixed threshold cannot do both. The gate is
    # semantic-only (FTS ts_rank is a different, tiny scale); --min-score forces an
    # absolute floor for either mode (0 shows everything).
    ABS_FLOOR, REL_RATIO = 0.18, 0.75
    if qv is not None and rows:
        top = max(float(r.score or 0) for r in rows)
        floor = args.min_score if args.min_score is not None else max(ABS_FLOOR, top * REL_RATIO)
    else:
        floor = args.min_score if args.min_score is not None else 0.0
    kept = [r for r in rows if float(r.score or 0) >= floor]

    print(f"\n=== {mode} | query: {args.query!r} | {len(kept)} result(s) "
          f"(score>={floor:.2f}) ===")
    if not kept:
        hint = (f"{len(rows)} weak match(es) below {floor:.2f} hidden; "
                f"show with --min-score 0" if rows
                else "try --mode fts, loosen filters, or another query")
        print(f"(no relevant matches — {hint})")
        return
    rows = kept
    for r in rows:
        ts = (f"{int(r.start_sec // 60)}:{int(r.start_sec % 60):02d}-"
              f"{int(r.end_sec // 60)}:{int(r.end_sec % 60):02d}")
        print(f"  [{ts}] {r.topic}  ({r.subject})  score={float(r.score or 0):.3f}  "
              f"video={str(r.video_id)[:8]} seg={r.seg_index}")


if __name__ == "__main__":
    main()
