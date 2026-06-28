"""
pipeline.py — orchestrate ALL stages for ONE video, in the right order, with the
voice/no-voice router deciding the path. Per-stage timing and VRAM logging make
the run observable; transcript checkpointing makes it resumable.

Order (each heavy model loaded -> used -> freed before the next):
  ingest audio -> detect speech -> ROUTE -> plan+extract frames (density by path)
  -> transcribe (voice only) -> audio features -> visual stack -> NLP
  -> segment (path-specific) -> attach signals -> LLM tag (path-specific prompt)
  -> embed -> store (Postgres) -> export (results JSON)
"""
from __future__ import annotations
import time
import uuid
from pathlib import Path

from . import audio, ingest, nlp_stage, segment, tagging
from .export import write_results_json
from .router import SILENT, VOICE, decide
from .storage import store
from .utils import (load_checkpoint, log, save_checkpoint, timer, capture_runtime)


def _video_id(path: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, path))


def process_one_video(video_path: str, cfg: dict, *, embedder, nlp,
                      engine=None, device: str = "cuda") -> dict:
    t_all = time.time()
    work = Path(cfg["WORK_DIR"])
    results_dir = work / cfg["RESULTS_SUBDIR"]
    frames_dir = work / "frames"
    audio_path = work / "audio.wav"

    P: dict = {"video_id": _video_id(video_path), "source_path": video_path,
               "transcript": [], "language": None, "audio_features": {},
               "frame_analyses": [], "nlp": {}, "segments": [],
               "stage_timings": {}, "status": "processing",
               # provenance of WHERE this ran (Kaggle), captured here so the
               # laptop sync reports the true processing env, not its own.
               "runtime": capture_runtime(cfg)}

    # ---- Stage 1: ingest audio + probe duration ----
    with timer(P["stage_timings"], "ingest_audio"):
        P["duration"] = ingest.probe_duration(video_path)
        wav_ok = ingest.extract_audio(video_path, audio_path)

    # ---- Stage 1.5: speech detection -> ROUTE ----
    has_speech, rms_db = (audio.detect_speech(audio_path, cfg["SILENCE_DB"])
                          if wav_ok else (False, -99.0))

    # transcribe early (voice only) so the route's speech_sec is exact; cache it
    transcribe_out = {"transcript": [], "language": None, "full_text": "",
                      "speech_sec": 0.0, "language_prob": None}
    if has_speech:
        ckpt = load_checkpoint(cfg["WORK_DIR"], cfg["CHECKPOINT_SUBDIR"], P["video_id"])
        if ckpt and ckpt.get("transcript"):
            log("resume: reusing cached transcript")
            transcribe_out = ckpt
        else:
            with timer(P["stage_timings"], "transcribe"):
                transcribe_out = audio.transcribe(
                    audio_path, model_name=cfg["WHISPER_MODEL"], device=device,
                    beam_size=cfg["WHISPER_BEAM"])
            save_checkpoint(cfg["WORK_DIR"], cfg["CHECKPOINT_SUBDIR"],
                            P["video_id"], transcribe_out)

    route = decide(has_speech=has_speech, mean_rms_db=rms_db,
                   speech_sec=transcribe_out["speech_sec"], cfg=cfg)
    P.update({"transcript": transcribe_out["transcript"],
              "language": transcribe_out["language"],
              "has_speech": route.has_speech, "tagging_path": route.path,
              "audio_features": {"mean_rms_db": rms_db,
                                 "speech_sec": transcribe_out["speech_sec"],
                                 "language_prob": transcribe_out["language_prob"]}})
    log(f"ROUTE = {route.path.upper()} :: {route.reason}")

    # ---- Stage 1b: frames (density chosen by route) ----
    with timer(P["stage_timings"], "extract_frames"):
        times = ingest.plan_frame_times(
            video_path, P["duration"], max_frames=route.max_frames,
            use_scene_cuts=cfg["USE_SCENE_CUTS"])
        P["frame_analyses"] = ingest.extract_frames_at(video_path, times, frames_dir)
    log(f"frames: {len(P['frame_analyses'])} (cap {route.max_frames}, path {route.path})")

    # ---- audio features (voice path; cheap) ----
    if route.path == VOICE and wav_ok:
        with timer(P["stage_timings"], "audio_features"):
            P["audio_features"].update(
                audio.audio_features(audio_path, P["duration"],
                                     transcribe_out["full_text"]))

    # ---- Stage 2B: visual stack ----
    from .visual import analyze_frames
    with timer(P["stage_timings"], "visual"):
        analyze_frames(P["frame_analyses"], cfg, device,
                       is_silent=(route.path == SILENT))

    # ---- Stage 3: NLP (voice path only; needs text) ----
    win_emb = None
    windows = []
    with timer(P["stage_timings"], "nlp"):
        P["nlp"] = nlp_stage.enrich(transcribe_out["full_text"], embedder, nlp)
        if route.path == VOICE:
            windows = nlp_stage.build_windows(P["transcript"], cfg["WINDOW_SEC"])
            win_emb = nlp_stage.embed_windows(windows, embedder)

    # ---- Stage 5: segmentation (path-specific) ----
    with timer(P["stage_timings"], "segmentation"):
        if route.path == VOICE:
            segs = segment.segment_voiced(windows, win_emb, P["duration"], cfg)
        else:
            segs = segment.segment_silent(P["frame_analyses"], P["duration"], cfg)
        P["segments"] = segment.attach_signals(segs, P["transcript"],
                                               P["frame_analyses"])
    log(f"segments: {len(P['segments'])}")

    # ---- Stage 4: LLM fusion (path-specific prompt) ----
    with timer(P["stage_timings"], "llm"):
        tagging.tag_segments(P, route.path, cfg, device)
    seg_emb = tagging.embed_segments(P, embedder)

    # ---- Stage 6: store + export ----
    if engine is not None:
        with timer(P["stage_timings"], "store"):
            store(P, seg_emb, engine)
    res, path = write_results_json(P, results_dir)

    P["status"] = "complete"
    P["stage_timings"]["total"] = round(time.time() - t_all, 2)
    topics = sorted({s["topic"] for s in res["segments"] if s["topic"]})
    log(f"DONE {Path(video_path).name}: {len(P['segments'])} segs, "
        f"{P['stage_timings']['total'] / 60:.1f} min, path={route.path}, "
        f"topics={topics} -> {path.name}")
    return {"video": Path(video_path).name, "video_id": P["video_id"][:8],
            "path": route.path, "segments": len(P["segments"]),
            "minutes": round(P["stage_timings"]["total"] / 60, 1),
            "topics": topics, "result_file": path.name}
