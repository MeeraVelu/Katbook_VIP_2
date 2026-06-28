"""
sync_results.py — pull processed video results from cloud Postgres down to your
laptop's  results/  folder so they open straight in VS Code.

WHY THIS EXISTS
---------------
Kaggle cannot write to your laptop. The pipeline therefore writes every result to
your cloud Postgres (Neon/Supabase) — the single durable source of truth. This
script runs ON YOUR LAPTOP, reads that same database, and mirrors each video into
one clean  results/<video_name>.json  (identical in shape to the JSON the Kaggle
notebook itself writes). Run it with --watch and the results/ folder fills in by
itself while the notebook is still processing on Kaggle.

USAGE (from  D:\\Katbook_VIP_2 ):
    pip install -r requirements-local.txt
    # give it the DB URL (either is fine):
    #   set DATABASE_URL=postgresql://user:pass@host/db      (Windows cmd)
    #   $env:DATABASE_URL="postgresql://..."                 (PowerShell)
    #   ...or put the URL on one line in  db_url.txt  next to this file.
    python sync_results.py            # one-shot
    python sync_results.py --watch    # keep mirroring every 30s (Ctrl+C to stop)

This file deliberately re-derives the SAME JSON that katbook_vip/export.py builds
on Kaggle, so a video looks the same whether the file came from the notebook run
or from this sync. Only SQLAlchemy + psycopg2 are required (no GPU, no ML deps).
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESULTS_DIR = HERE / "results"


# --------------------------------------------------------------------------- #
# DB URL resolution (env var first, then db_url.txt) — same rule as the notebook
# --------------------------------------------------------------------------- #
def get_database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        f = HERE / "db_url.txt"
        if f.exists():
            url = f.read_text(encoding="utf-8").strip()
    if not url:
        sys.exit(
            "No DATABASE_URL. Set the env var or create db_url.txt next to this "
            "script (see the usage block at the top of sync_results.py)."
        )
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg2://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return url


def _safe_stem(source_path: str | None, video_id: str) -> str:
    """Readable, filesystem-safe filename from the source video name."""
    if source_path:
        base = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(source_path).stem).strip("_")
        if base:
            return base
    return f"results_{str(video_id)[:8]}"


def _j(x):
    """JSONB columns return as dict/list already; tolerate raw strings too."""
    if isinstance(x, (list, dict)):
        return x
    return json.loads(x) if x else {}


def _recover_llm(raw: str) -> dict:
    """Recover fields from an LLM output that failed strict json.loads — strips
    ```json fences, repairs truncation, falls back to regex field extraction."""
    t = (raw or "").strip()
    t = re.sub(r"^```(?:json)?", "", t).strip()
    t = re.sub(r"```$", "", t).strip()
    m = re.search(r"\{.*", t, re.DOTALL)
    if not m:
        return {}
    js = m.group(0)
    for cand in (js, js + "}", js + '"}', js + '"}}',
                 js[: js.rfind("}") + 1] if "}" in js else js):
        try:
            return json.loads(cand)
        except Exception:
            pass

    def grab(key):
        mm = re.search(rf'"{key}"\s*:\s*"([^"]*)"', js)
        return mm.group(1) if mm else None

    tags_m = re.search(r'"tags"\s*:\s*\[(.*?)\]', js, re.DOTALL)
    out = {
        "topic": grab("topic"), "subject": grab("subject"),
        "grade_level": grab("grade_level"), "difficulty": grab("difficulty"),
        "content_type": grab("content_type"), "summary": grab("summary"),
        "tags": [x.strip().strip('"') for x in tags_m.group(1).split(",")
                 if x.strip()] if tags_m else [],
    }
    return {k: v for k, v in out.items() if v}


def _llm(raw_field) -> dict:
    d = _j(raw_field)
    if isinstance(d, dict) and "_parse_error" in d:
        recovered = _recover_llm(d["_parse_error"])
        if recovered:
            return recovered
    return d if isinstance(d, dict) else {}


def build_results(engine) -> list[dict]:
    """Rebuild the same flat result dict shape as katbook_vip/export.py, but from
    the stored DB rows (including has_speech / tagging_path / language)."""
    from sqlalchemy import text as sql
    out = []
    with engine.connect() as cx:
        videos = cx.execute(sql(
            "SELECT video_id, source_path, duration, language, has_speech, "
            "tagging_path, stage_timings, created_at "
            "FROM videos ORDER BY created_at DESC")).mappings().all()
        for v in videos:
            segs = cx.execute(sql(
                "SELECT seg_index, start_sec, end_sec, scenes, objects, ocr, llm "
                "FROM segments WHERE video_id=:v ORDER BY seg_index"),
                {"v": str(v["video_id"])}).mappings().all()
            st = _j(v["stage_timings"])
            result = {
                "video_id": str(v["video_id"])[:8],
                "source": v["source_path"],
                "processed_at": v["created_at"].isoformat() if v["created_at"] else None,
                "os": f"{platform.system()} {platform.release()}",
                "python": platform.python_version(),
                "duration_sec": round(float(v["duration"] or 0), 2),
                "language": v["language"],
                "has_speech": v["has_speech"],
                "tagging_path": v["tagging_path"],
                "segment_count": len(segs),
                "pipeline_time_sec": round(sum(st.values()), 1)
                if isinstance(st, dict) and st else None,
                "stage_timings": st if isinstance(st, dict) else {},
                "segments": [],
            }
            for i, s in enumerate(segs, start=1):
                llm = _llm(s["llm"]); scenes = _j(s["scenes"]); objects = _j(s["objects"])
                result["segments"].append({
                    "segment": i,
                    "start": round(float(s["start_sec"]), 1),
                    "end": round(float(s["end_sec"]), 1),
                    "topic": llm.get("topic"),
                    "subject": llm.get("subject"),
                    "grade": llm.get("grade_level"),
                    "difficulty": llm.get("difficulty"),
                    "content_type": llm.get("content_type"),
                    "tags": llm.get("tags", []),
                    "subtopics": llm.get("subtopics", []),
                    "summary": llm.get("summary"),
                    "confidence": llm.get("confidence"),
                    "dominant_scene": (scenes[0] if scenes else None),
                    "objects_detected": objects,
                })
            out.append(result)
    return out


def export_once(engine) -> int:
    RESULTS_DIR.mkdir(exist_ok=True, parents=True)
    all_results = build_results(engine)
    for r in all_results:
        path = RESULTS_DIR / f"{_safe_stem(r['source'], r['video_id'])}.json"
        path.write_text(json.dumps(r, indent=2, default=str), encoding="utf-8")
        speech = "voice" if r.get("has_speech") else "silent"
        print(f"  wrote {path.name}  ({r['segment_count']} segments, {speech})")
    combined = RESULTS_DIR / "all_results.json"
    combined.write_text(json.dumps(all_results, indent=2, default=str), encoding="utf-8")
    print(f"Synced {len(all_results)} video(s) -> {RESULTS_DIR}  (+ all_results.json)")
    return len(all_results)


def main():
    ap = argparse.ArgumentParser(description="Mirror cloud Postgres results into ./results")
    ap.add_argument("--watch", action="store_true",
                    help="re-sync every --interval seconds (good while Kaggle runs)")
    ap.add_argument("--interval", type=int, default=30)
    args = ap.parse_args()

    try:
        from sqlalchemy import create_engine
    except ImportError:
        sys.exit("Missing deps. Run:  pip install -r requirements-local.txt")

    engine = create_engine(get_database_url(), pool_pre_ping=True)
    if args.watch:
        print(f"Watching DB; syncing every {args.interval}s. Ctrl+C to stop.")
        while True:
            try:
                export_once(engine)
            except Exception as e:
                print("sync error:", e)
            time.sleep(args.interval)
    else:
        export_once(engine)


if __name__ == "__main__":
    main()
