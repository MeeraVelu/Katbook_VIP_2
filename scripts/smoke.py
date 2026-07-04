#!/usr/bin/env python
"""
smoke.py — end-to-end pipeline wiring check on CPU, no GPU required.

Generates a 10-second clip, forces the ``smoke`` profile (tiny Whisper/CLIP, the
MiniLM embedder, the deterministic ``stub`` tagger — no LLM download), runs the
FULL pipeline JSON-only (no Postgres needed), and asserts a well-formed results
JSON came out. This proves ingest -> route -> frames -> visual -> segment -> tag
-> embed -> export are correctly wired together without a GPU.

    python scripts/smoke.py
    make smoke
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# ensure the smoke profile + CPU + no DB BEFORE importing the pipeline/config
os.environ.setdefault("KVIP_PROFILE", "smoke")
os.environ.setdefault("KVIP_TAGGING_BACKEND", "stub")
os.environ.setdefault("KVIP_ENABLE_DB", "0")
os.environ.setdefault("KVIP_FFMPEG_HWACCEL", "none")
os.environ.setdefault("KVIP_LOG_FORMAT", "plain")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    from pipeline import load_config, process_one_video
    from pipeline.logging_config import configure_logging
    from scripts.make_test_video import make_test_video

    configure_logging()
    work = Path(tempfile.mkdtemp(prefix="kvip_smoke_"))
    clip = make_test_video(str(work / "smoke_clip.mp4"))
    print(f"generated test clip: {clip}")

    cfg = load_config({"WORK_DIR": str(work), "ENABLE_DB": False})

    # shared small models (CPU): MiniLM embedder + spaCy
    import spacy
    from sentence_transformers import SentenceTransformer

    embedder = SentenceTransformer(cfg["EMBED_MODEL"], device="cpu")
    try:
        nlp = spacy.load("en_core_web_sm")
    except Exception:
        import subprocess

        subprocess.run([sys.executable, "-m", "spacy", "download", "en_core_web_sm"], check=False)
        nlp = spacy.load("en_core_web_sm")

    summary = process_one_video(clip, cfg, embedder=embedder, nlp=nlp, engine=None, device="cpu")
    print("summary:", summary)

    results_dir = work / cfg["RESULTS_SUBDIR"]
    files = list(results_dir.glob("*.json"))
    assert files, "no results JSON was written"
    import json

    doc = json.loads(files[0].read_text())
    assert "segments" in doc and "video" in doc, "results JSON missing expected keys"
    assert doc["segment_count"] >= 1, "expected at least one segment"
    print(
        f"\nSMOKE PASS: {files[0].name} — {doc['segment_count']} segment(s), "
        f"path={doc.get('tagging_path')}, tagger=stub"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as e:
        print(f"SMOKE FAIL: {e}")
        raise SystemExit(1) from e
