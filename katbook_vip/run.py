"""
run.py — the entry point. Discover videos, apply the selection rule, load the
shared small models once (embedder + spaCy), then process the selected videos in
a loop where ONE video failing never kills the batch.

    from katbook_vip import run_batch, load_config
    run_batch(load_config({"PROCESS": "all", "PROFILE": "fast"}))

or from the command line:

    python -m katbook_vip --process all --profile fast
"""
from __future__ import annotations
import glob
import uuid
from pathlib import Path

from .config import load_config
from .pipeline import process_one_video
from .storage import existing_video_ids, make_engine, normalize_db_url
from .utils import gpu_banner, log


def discover_videos(cfg: dict) -> list[str]:
    return sorted(glob.glob(cfg["VIDEO_GLOB"], recursive=True))


def select_videos(cfg: dict, all_videos: list[str]) -> list[str]:
    """Resolve CONFIG['PROCESS'] to a concrete list. No silent fallback: an
    unmatched selection processes NOTHING and says so (never the wrong video).

    Accepts: "all" | "first" | N | "name-substring" | a LIST [2, 4] or a
    comma-separated string "2,4" / "pendulum,chemistry" to pick several at once."""
    raw = cfg.get("PROCESS", "all")

    # MULTI-SELECT: a list, or a comma-separated string -> resolve each item, dedupe.
    if isinstance(raw, (list, tuple)) or (isinstance(raw, str) and "," in raw):
        items = (list(raw) if isinstance(raw, (list, tuple))
                 else [x.strip() for x in raw.split(",") if x.strip()])
        chosen, seen = [], set()
        for it in items:
            for v in select_videos({**cfg, "PROCESS": it}, all_videos):
                if v not in seen:
                    seen.add(v); chosen.append(v)
        return chosen

    if isinstance(raw, int) or (isinstance(raw, str) and raw.strip().isdigit()):
        k = int(raw)
        chosen = all_videos[k - 1:k] if 1 <= k <= len(all_videos) else []
        if not chosen:
            log(f"PROCESS={raw} out of range (1..{len(all_videos)}); nothing selected", "WARN")
        return chosen
    sel = str(raw).strip().lower()
    if sel == "all":
        return all_videos
    if sel in ("first", "one", "single"):
        return all_videos[:1]
    exact = [v for v in all_videos if Path(v).name.lower() == sel]
    chosen = exact or [v for v in all_videos if sel in v.lower()]
    if not chosen:
        log(f"PROCESS={raw!r} matched no video; set it to a number from the list", "WARN")
    elif len(chosen) > 1:
        log(f"{raw!r} matched {len(chosen)} videos -> processing all "
            f"(use a NUMBER to pick one)", "WARN")
    return chosen


def _load_shared_models(cfg: dict, device: str):
    from sentence_transformers import SentenceTransformer
    import spacy
    log("loading shared embedder (MiniLM) + spaCy once for the whole batch")
    embedder = SentenceTransformer(cfg["EMBED_MODEL"], device=device)
    try:
        nlp = spacy.load("en_core_web_sm")
    except Exception:
        import subprocess, sys
        subprocess.run([sys.executable, "-m", "spacy", "download",
                        "en_core_web_sm"], check=False)
        nlp = spacy.load("en_core_web_sm")
    return embedder, nlp


def run_batch(cfg: dict | None = None) -> list[dict]:
    cfg = cfg or load_config()
    log(gpu_banner())
    try:
        import torch
        device = "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        device = "cpu"

    all_videos = discover_videos(cfg)
    log(f"discovered {len(all_videos)} video(s):")
    for i, v in enumerate(all_videos, 1):
        log(f"   {i}. {Path(v).name}")
    selected = select_videos(cfg, all_videos)

    # DB engine (optional) + skip-existing set
    engine = None
    db_url = normalize_db_url(cfg.get("DATABASE_URL"))
    if cfg.get("ENABLE_DB") and db_url:
        try:
            engine = make_engine(db_url)
            log("Postgres connected")
        except Exception as e:
            log(f"Postgres unavailable ({str(e)[:60]}); JSON-only", "WARN")
    else:
        log("no DATABASE_URL -> results saved to JSON only (not Postgres)", "WARN")

    skip = (existing_video_ids(engine)
            if engine and cfg.get("SKIP_EXISTING") else set())

    embedder, nlp = _load_shared_models(cfg, device)

    log(f"=== BATCH (PROCESS={cfg.get('PROCESS')!r}, PROFILE={cfg['PROFILE']}): "
        f"{len(selected)} of {len(all_videos)} video(s) ===")
    summary = []
    for n, vpath in enumerate(selected, 1):
        vid = str(uuid.uuid5(uuid.NAMESPACE_URL, vpath))
        if vid in skip:
            log(f"[{n}/{len(selected)}] SKIP (already in DB): {Path(vpath).name}")
            summary.append({"video": Path(vpath).name, "skipped": "already in DB"})
            continue
        log(f"[{n}/{len(selected)}] >>> {Path(vpath).name}")
        try:
            summary.append(process_one_video(vpath, cfg, embedder=embedder,
                                             nlp=nlp, engine=engine, device=device))
        except Exception as e:
            log(f"FAILED {Path(vpath).name}: {e}", "ERROR")
            import traceback; traceback.print_exc()
            summary.append({"video": Path(vpath).name, "error": str(e)[:200]})

    log("=== BATCH COMPLETE ===")
    for s in summary:
        log(f"   {s}")
    return summary


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="Katbook VIP pipeline")
    ap.add_argument("--process", default=None, help="all | first | N | substring")
    ap.add_argument("--profile", default=None, choices=["fast", "balanced", "quality"])
    ap.add_argument("--video-glob", default=None)
    ap.add_argument("--no-db", action="store_true", help="skip Postgres, JSON only")
    args = ap.parse_args()
    overrides = {}
    if args.process is not None:
        overrides["PROCESS"] = args.process
    if args.profile is not None:
        overrides["PROFILE"] = args.profile
    if args.video_glob is not None:
        overrides["VIDEO_GLOB"] = args.video_glob
    if args.no_db:
        overrides["ENABLE_DB"] = False
    run_batch(load_config(overrides))


if __name__ == "__main__":
    main()
