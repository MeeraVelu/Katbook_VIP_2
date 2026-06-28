"""
export_results.py — pull processed video results from cloud Postgres to local JSON.

The Kaggle notebook stores every processed video in your cloud Postgres (Neon/Supabase).
This script runs ON YOUR LAPTOP, connects to that same database, and writes one clean
results_<id>.json per video into ./results/ — so you can open them in VS Code.

USAGE (from d:\\Katbook_VIP_2):
    1. one-time install:   pip install sqlalchemy psycopg2-binary
    2. give it the DB URL, either:
         - set an env var:   set DATABASE_URL=postgresql://user:pass@host/db   (Windows cmd)
                             $env:DATABASE_URL="postgresql://..."             (PowerShell)
         - OR create a file  db_url.txt  next to this script with the URL on one line
    3. run:                python export_results.py
       (add --watch to re-export every 60s, e.g. while you re-run the notebook)
"""
import os
import re
import sys
import json
import time
import argparse
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESULTS_DIR = HERE / "results"


def file_stem(source_path, video_id):
    """Build a readable, filesystem-safe file name from the source video name.
    e.g. '.../Simple Pendulum _ Science Experiment.mp4' -> 'Simple_Pendulum_Science_Experiment'.
    Falls back to the short video_id if there's no source path."""
    if source_path:
        base = Path(source_path).stem                      # filename without extension
        base = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("_")
        if base:
            return base
    return f"results_{str(video_id)[:8]}"


def get_database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        f = HERE / "db_url.txt"
        if f.exists():
            url = f.read_text(encoding="utf-8").strip()
    if not url:
        sys.exit("No DATABASE_URL. Set the env var or create db_url.txt next to this script "
                 "(see usage at the top of export_results.py).")
    # SQLAlchemy + psycopg2 wants the +psycopg2 driver prefix
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg2://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return url


def _j(x):
    """JSONB columns come back as dict/list already; tolerate raw strings too."""
    if isinstance(x, (list, dict)):
        return x
    return json.loads(x) if x else {}


def recover_llm(raw: str) -> dict:
    """Recover fields from an LLM output that failed strict json.loads — strips ```json
    fences, repairs truncation, and falls back to regex field extraction."""
    import re
    t = (raw or "").strip()
    t = re.sub(r"^```(?:json)?", "", t).strip()
    t = re.sub(r"```$", "", t).strip()
    m = re.search(r"\{.*", t, re.DOTALL)
    if not m:
        return {}
    js = m.group(0)
    # try as-is, then with closing braces appended, then trimmed to last complete brace
    for cand in (js, js + "}", js + '"}', js + '"}}', js[:js.rfind("}") + 1] if "}" in js else js):
        try:
            return json.loads(cand)
        except Exception:
            pass
    # regex fallback: pull the individual fields that completed before truncation
    def grab(key):
        mm = re.search(rf'"{key}"\s*:\s*"([^"]*)"', js)
        return mm.group(1) if mm else None
    tags_m = re.search(r'"tags"\s*:\s*\[(.*?)\]', js, re.DOTALL)
    out = {"topic": grab("topic"), "subject": grab("subject"),
           "grade_level": grab("grade_level"), "difficulty": grab("difficulty"),
           "content_type": grab("content_type"), "summary": grab("summary"),
           "tags": [x.strip().strip('"') for x in tags_m.group(1).split(",") if x.strip()] if tags_m else []}
    return {k: v for k, v in out.items() if v}


def _llm(raw_field):
    """Normalize a stored llm value: parse JSONB, and recover if it's a _parse_error."""
    d = _j(raw_field)
    if isinstance(d, dict) and "_parse_error" in d:
        recovered = recover_llm(d["_parse_error"])
        if recovered:
            return recovered
    return d


def build_results(engine):
    from sqlalchemy import text as sqltext
    import platform
    out = []
    with engine.connect() as cx:
        videos = cx.execute(sqltext(
            "SELECT video_id, source_path, duration, language, stage_timings, created_at "
            "FROM videos ORDER BY created_at DESC")).mappings().all()
        for v in videos:
            segs = cx.execute(sqltext(
                "SELECT seg_index, start_sec, end_sec, scenes, objects, llm "
                "FROM segments WHERE video_id=:v ORDER BY seg_index"),
                {"v": str(v["video_id"])}).mappings().all()
            st = _j(v["stage_timings"])
            results = {
                "video_id": str(v["video_id"])[:8],
                "source": v["source_path"],
                "processed_at": v["created_at"].isoformat() if v["created_at"] else None,
                "os": f"{platform.system()} {platform.release()}",
                "python": platform.python_version(),
                "duration_sec": round(float(v["duration"] or 0), 2),
                "language": v["language"],
                "segment_count": len(segs),
                "pipeline_time_sec": round(sum(st.values()), 1) if isinstance(st, dict) and st else None,
                "segments": [],
            }
            for i, s in enumerate(segs, start=1):
                llm = _llm(s["llm"]); scenes = _j(s["scenes"]); objects = _j(s["objects"])
                results["segments"].append({
                    "segment": i,
                    "start": round(float(s["start_sec"]), 1),
                    "end": round(float(s["end_sec"]), 1),
                    "topic": llm.get("topic"),
                    "difficulty": llm.get("difficulty"),
                    "subject": llm.get("subject"),
                    "grade": llm.get("grade_level"),
                    "content_type": llm.get("content_type"),
                    "tags": llm.get("tags", []),
                    "summary": llm.get("summary"),
                    "confidence": llm.get("confidence"),
                    "dominant_scene": (scenes[0] if scenes else None),
                    "objects_detected": objects,
                })
            out.append(results)
    return out


def export_once(engine):
    RESULTS_DIR.mkdir(exist_ok=True, parents=True)
    all_results = build_results(engine)
    for r in all_results:
        path = RESULTS_DIR / f"{file_stem(r['source'], r['video_id'])}.json"
        path.write_text(json.dumps(r, indent=2, default=str), encoding="utf-8")
        print(f"  wrote {path.name}  ({r['segment_count']} segments)")
    # also a combined file for convenience
    combined = RESULTS_DIR / "all_results.json"
    combined.write_text(json.dumps(all_results, indent=2, default=str), encoding="utf-8")
    print(f"Exported {len(all_results)} video(s) -> {RESULTS_DIR}  (+ all_results.json)")
    return len(all_results)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--watch", action="store_true", help="re-export every --interval seconds")
    ap.add_argument("--interval", type=int, default=60)
    args = ap.parse_args()

    try:
        from sqlalchemy import create_engine
    except ImportError:
        sys.exit("Missing deps. Run:  pip install sqlalchemy psycopg2-binary")

    engine = create_engine(get_database_url(), pool_pre_ping=True)
    if args.watch:
        print(f"Watching DB; exporting every {args.interval}s. Ctrl+C to stop.")
        while True:
            try:
                export_once(engine)
            except Exception as e:
                print("export error:", e)
            time.sleep(args.interval)
    else:
        export_once(engine)


if __name__ == "__main__":
    main()
