"""
export.py — write the clean, flat, human-readable results JSON that lands in the
results/ folder (and that the local sync watcher mirrors into VS Code).

This is the artifact a human reads: one summary block + one row per segment with
topic / subject / grade / difficulty / tags / summary / confidence, plus the
dominant scene and (only-when-meaningful) detected objects.
"""
from __future__ import annotations
import json
import platform
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


def _safe_stem(source_path: str, video_id: str) -> str:
    if source_path:
        base = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(source_path).stem).strip("_")
        if base:
            return base
    return f"results_{video_id[:8]}"


def _dominant_scene(seg: dict, frames: list[dict]) -> str | None:
    fr = [f for f in frames
          if seg["start"] <= f["time"] < seg["end"] and f.get("scene")]
    if fr:
        return Counter(f["scene"] for f in fr).most_common(1)[0][0]
    return (seg.get("scenes") or [None])[0]


_DIFF_RANK = {"beginner": 0, "intermediate": 1, "advanced": 2, "expert": 3}


def video_rollup(seg_rows: list[dict]) -> dict:
    """Video-level summary aggregated from the per-segment tags: the majority
    subject/grade, the hardest difficulty seen, the primary (longest-segment)
    topic, the ordered list of topics, and the de-duplicated union of all tags.

    Shared shape so the Kaggle-written JSON and the laptop-synced JSON match
    exactly. `seg_rows` are the already-flattened segment dicts.
    """
    subjects = [s["subject"] for s in seg_rows if s.get("subject")]
    grades = [s["grade"] for s in seg_rows if s.get("grade")]
    diffs = [s["difficulty"] for s in seg_rows if s.get("difficulty")]
    primary = None
    if seg_rows:
        primary = max(seg_rows, key=lambda s: (s.get("end", 0) - s.get("start", 0))).get("topic")
    topics, seen = [], set()
    for s in seg_rows:
        tp = s.get("topic")
        if tp and tp not in seen:
            seen.add(tp); topics.append(tp)
    all_tags, seen_t = [], set()
    for s in seg_rows:
        for tg in s.get("tags", []):
            if tg and tg not in seen_t:
                seen_t.add(tg); all_tags.append(tg)
    return {
        "subject": Counter(subjects).most_common(1)[0][0] if subjects else None,
        "grade": Counter(grades).most_common(1)[0][0] if grades else None,
        "difficulty": max(diffs, key=lambda d: _DIFF_RANK.get(d, 0)) if diffs else None,
        "primary_topic": primary,
        "topics": topics,
        "all_tags": all_tags,
    }


def build_result(payload: dict) -> dict:
    frames = payload.get("frame_analyses", [])
    rt = payload.get("runtime", {}) or {}
    seg_rows = [{
        "segment": i,
        "start": round(float(s["start"]), 1),
        "end": round(float(s["end"]), 1),
        "topic": (s.get("llm") or {}).get("topic"),
        "subject": (s.get("llm") or {}).get("subject"),
        "grade": (s.get("llm") or {}).get("grade_level"),
        "difficulty": (s.get("llm") or {}).get("difficulty"),
        "content_type": (s.get("llm") or {}).get("content_type"),
        "tags": (s.get("llm") or {}).get("tags", []),
        "subtopics": (s.get("llm") or {}).get("subtopics", []),
        "summary": (s.get("llm") or {}).get("summary"),
        "confidence": (s.get("llm") or {}).get("confidence"),
        "dominant_scene": _dominant_scene(s, frames),
        # objects are already suppressed upstream for synthetic scenes
        "objects_detected": s.get("objects", []),
    } for i, s in enumerate(payload["segments"], start=1)]
    return {
        "video_id": payload["video_id"][:8],
        "source": payload["source_path"],
        "processed_at": datetime.now(timezone.utc).isoformat(),
        # provenance reflects WHERE it was processed (Kaggle), from payload.runtime,
        # not the machine writing this file.
        "os": rt.get("os") or f"{platform.system()} {platform.release()}",
        "python": rt.get("python") or platform.python_version(),
        "gpu": rt.get("gpu"),
        "profile": rt.get("profile"),
        "package_version": rt.get("package_version"),
        "duration_sec": round(float(payload.get("duration") or 0), 2),
        "language": payload.get("language"),
        "has_speech": payload.get("has_speech"),
        "tagging_path": payload.get("tagging_path"),
        "segment_count": len(seg_rows),
        "pipeline_time_sec": round(sum(payload.get("stage_timings", {}).values()), 1),
        "stage_timings": payload.get("stage_timings", {}),
        "segments": seg_rows,
        "video": video_rollup(seg_rows),
    }


def write_results_json(payload: dict, results_dir: Path) -> tuple[dict, Path]:
    results_dir.mkdir(parents=True, exist_ok=True)
    res = build_result(payload)
    path = results_dir / f"{_safe_stem(payload['source_path'], payload['video_id'])}.json"
    path.write_text(json.dumps(res, indent=2, default=str))
    return res, path
