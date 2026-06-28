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


def build_result(payload: dict) -> dict:
    frames = payload.get("frame_analyses", [])
    return {
        "video_id": payload["video_id"][:8],
        "source": payload["source_path"],
        "processed_at": datetime.now(timezone.utc).isoformat(),
        "os": f"{platform.system()} {platform.release()}",
        "python": platform.python_version(),
        "duration_sec": round(float(payload.get("duration") or 0), 2),
        "language": payload.get("language"),
        "has_speech": payload.get("has_speech"),
        "tagging_path": payload.get("tagging_path"),
        "segment_count": len(payload["segments"]),
        "pipeline_time_sec": round(sum(payload.get("stage_timings", {}).values()), 1),
        "stage_timings": payload.get("stage_timings", {}),
        "segments": [{
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
        } for i, s in enumerate(payload["segments"], start=1)],
    }


def write_results_json(payload: dict, results_dir: Path) -> tuple[dict, Path]:
    results_dir.mkdir(parents=True, exist_ok=True)
    res = build_result(payload)
    path = results_dir / f"{_safe_stem(payload['source_path'], payload['video_id'])}.json"
    path.write_text(json.dumps(res, indent=2, default=str))
    return res, path
