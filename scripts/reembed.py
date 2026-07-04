#!/usr/bin/env python
"""
reembed.py — (re)compute segment embeddings with the production embedder.

Use this when importing legacy POC rows (MiniLM, 384-d) into the production schema
(BGE-M3, 1024-d): the vector dimensions are incompatible, so the old vectors can't
be reused. This script regenerates each segment's embedding from its stored text
(``summary`` -> ``transcript_text`` -> ``topic``) using the production embedder and
writes it back. Safe to re-run; only touches the ``embedding`` column.

    # embed only rows that currently have NULL embeddings:
    python scripts/reembed.py
    # re-embed EVERYTHING (e.g. after switching embedder):
    python scripts/reembed.py --all --batch 256
"""

from __future__ import annotations

import argparse
import os

from sqlalchemy import create_engine, text

from pipeline.storage import normalize_db_url


def _vec_literal(vec) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in vec) + "]"


def main() -> int:
    ap = argparse.ArgumentParser(description="Re-embed segments with the production embedder")
    ap.add_argument("--all", action="store_true", help="re-embed all rows, not just NULL ones")
    ap.add_argument("--batch", type=int, default=128)
    ap.add_argument("--model", default=os.environ.get("KVIP_EMBED_MODEL", "BAAI/bge-m3"))
    args = ap.parse_args()

    url = normalize_db_url(os.environ.get("DATABASE_URL"))
    if not url:
        raise SystemExit("DATABASE_URL is not set")
    engine = create_engine(url, pool_pre_ping=True, future=True)

    from sentence_transformers import SentenceTransformer

    print(f"loading embedder {args.model} (CPU is fine)")
    model = SentenceTransformer(args.model, device=os.environ.get("KVIP_DEVICE", "cpu"))

    where = "" if args.all else "WHERE embedding IS NULL"
    with engine.connect() as cx:
        rows = cx.execute(
            text(f"SELECT id, summary, transcript_text, topic FROM segments {where} ORDER BY id")
        ).fetchall()
    print(f"{len(rows)} segment(s) to embed")

    done = 0
    for i in range(0, len(rows), args.batch):
        chunk = rows[i : i + args.batch]
        texts = [(r.summary or r.transcript_text or r.topic or "untitled segment") for r in chunk]
        embs = model.encode(texts, normalize_embeddings=True)
        with engine.begin() as cx:
            for r, e in zip(chunk, embs, strict=False):
                cx.execute(
                    text("UPDATE segments SET embedding = CAST(:e AS vector) WHERE id=:id"),
                    {"e": _vec_literal(e.tolist()), "id": r.id},
                )
        done += len(chunk)
        print(f"  embedded {done}/{len(rows)}")
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
