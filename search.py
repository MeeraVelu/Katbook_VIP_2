"""
search.py — query processed videos straight from cloud Postgres (no Kaggle, no GPU).

Full-text + tag filters need only SQLAlchemy. Semantic search additionally needs
sentence-transformers (CPU is fine); it's used automatically if available.

USAGE (from d:\\Katbook_VIP_2):
    python search.py "time period of a pendulum"
    python search.py "rational numbers" --subject Mathematics --k 5
    python search.py "oscillation" --mode fts          # force keyword-only (no ML deps)

DB URL comes from env DATABASE_URL or db_url.txt (same as export_results.py).
"""
import os
import sys
import json
import argparse
from pathlib import Path

HERE = Path(__file__).resolve().parent


def get_db_url():
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


def embed(query):
    """Return a normalized embedding for semantic search, or None if unavailable."""
    try:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2", device="cpu")
        return model.encode([query], normalize_embeddings=True)[0].tolist()
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("--mode", choices=["auto", "semantic", "fts"], default="auto")
    ap.add_argument("--subject"); ap.add_argument("--grade"); ap.add_argument("--ctype")
    ap.add_argument("--k", type=int, default=5)
    args = ap.parse_args()

    from sqlalchemy import create_engine, text as sql
    eng = create_engine(get_db_url(), pool_pre_ping=True)

    filt, params = [], {"q": args.query, "k": args.k}
    if args.subject: filt.append("llm->>'subject' = :subject"); params["subject"] = args.subject
    if args.grade:   filt.append("llm->>'grade_level' = :grade"); params["grade"] = args.grade
    if args.ctype:   filt.append("llm->>'content_type' = :ctype"); params["ctype"] = args.ctype
    where = (" AND " + " AND ".join(filt)) if filt else ""

    qv = embed(args.query) if args.mode in ("auto", "semantic") else None
    if qv is not None:
        params["qv"] = str(qv)
        stmt = sql(f"""SELECT video_id, seg_index, start_sec, end_sec,
            llm->>'topic' AS topic, llm->>'subject' AS subject,
            1 - (embedding <=> :qv) AS score
            FROM segments WHERE TRUE {where} ORDER BY embedding <=> :qv LIMIT :k""")
        mode = "semantic (pgvector)"
    else:
        stmt = sql(f"""SELECT video_id, seg_index, start_sec, end_sec,
            llm->>'topic' AS topic, llm->>'subject' AS subject,
            ts_rank(fts, plainto_tsquery('english', :q)) AS score
            FROM segments WHERE fts @@ plainto_tsquery('english', :q) {where}
            ORDER BY score DESC LIMIT :k""")
        mode = "full-text (tsvector)"

    with eng.connect() as cx:
        rows = cx.execute(stmt, params).fetchall()

    print(f"\n=== {mode} | query: {args.query!r} | {len(rows)} result(s) ===")
    if not rows:
        print("(no matches — try --mode fts, loosen filters, or another query)")
        return
    for r in rows:
        ts = f"{int(r.start_sec//60)}:{int(r.start_sec%60):02d}-{int(r.end_sec//60)}:{int(r.end_sec%60):02d}"
        print(f"  [{ts}] {r.topic}  ({r.subject})  score={float(r.score or 0):.3f}  "
              f"video={str(r.video_id)[:8]} seg={r.seg_index}")


if __name__ == "__main__":
    main()
