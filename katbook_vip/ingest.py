"""
ingest.py — Stage 1. Turn a video file into the two inputs every later stage
needs: a 16 kHz mono WAV (Whisper-optimal) and a small set of sampled frames.

Speed lever (the big one): instead of a fixed frames-per-second that produces
30-60 frames regardless of content, we sample an ADAPTIVE number of frames:
  * voiced videos -> few frames (transcript leads; frames are a weak hint)
  * silent videos -> denser frames (frames carry ALL the meaning)
Optionally we add the few real visual-change moments (scene cuts) on top of
uniform anchors. Smooth animations have almost no hard cuts, so uniform anchors
are the reliable backbone; cuts are bonus detail when present.

CPU-only stage; no GPU, no model. Fully testable locally.
"""
from __future__ import annotations
import re
import subprocess
from pathlib import Path

from .utils import log


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def probe_duration(video_path: str) -> float:
    cp = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
               "-of", "default=nw=1:nk=1", video_path])
    try:
        return float(cp.stdout.strip())
    except Exception:
        return 0.0


def has_audio_stream(video_path: str) -> bool:
    cp = _run(["ffprobe", "-v", "error", "-select_streams", "a",
               "-show_entries", "stream=codec_name", "-of", "default=nw=1:nk=1",
               video_path])
    return bool(cp.stdout.strip())


def extract_audio(video_path: str, out_wav: Path) -> bool:
    """16 kHz mono PCM WAV. Returns False if the video has no audio stream."""
    if not has_audio_stream(video_path):
        log("no audio stream present -> silent video", "WARN")
        return False
    _run(["ffmpeg", "-y", "-i", video_path, "-ac", "1", "-ar", "16000",
          "-vn", "-f", "wav", str(out_wav), "-loglevel", "error"])
    return out_wav.exists()


def _scene_cut_times(video_path: str, threshold: float) -> list[float]:
    """Timestamps of hard visual changes via ffmpeg's scene score (one pass)."""
    cp = _run(["ffmpeg", "-i", video_path, "-vf",
               f"select='gt(scene,{threshold})',showinfo", "-f", "null", "-"])
    return [float(m) for m in re.findall(r"pts_time:([0-9.]+)", cp.stderr)]


def plan_frame_times(video_path: str, duration: float, *, max_frames: int,
                     use_scene_cuts: bool, scene_threshold: float = 0.3,
                     min_per_30s: float = 1.0) -> list[float]:
    """
    Decide WHICH timestamps to grab. Uniform anchors guarantee coverage;
    scene cuts add detail where the video actually changes. Result is capped
    at max_frames and de-duplicated.
    """
    if duration <= 0:
        return [0.0]
    # uniform anchors: ~min_per_30s per 30s, at least 4, never over the cap
    n_anchor = min(max_frames, max(4, int(duration / 30 * min_per_30s) + 1))
    anchors = [round(duration * i / (n_anchor + 1), 2) for i in range(1, n_anchor + 1)]

    times = set(anchors)
    if use_scene_cuts:
        for t in _scene_cut_times(video_path, scene_threshold):
            times.add(round(t, 2))

    ordered = sorted(t for t in times if 0 <= t <= duration)
    if len(ordered) > max_frames:  # keep the most spread-out
        step = len(ordered) / max_frames
        ordered = [ordered[int(i * step)] for i in range(max_frames)]
    return ordered or [0.0]


def extract_frames_at(video_path: str, times: list[float], out_dir: Path,
                      scale_w: int = 224) -> list[dict]:
    """
    Extract one JPEG per requested timestamp with fast seek. Downscaled to
    scale_w px wide (plenty for CLIP/YOLO/OCR, much faster I/O).
    Returns [{"index","time","path"}], skipping any frame ffmpeg couldn't grab.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    for f in out_dir.glob("frame_*.jpg"):
        f.unlink()  # clear the previous video's frames
    frames = []
    for i, t in enumerate(times):
        path = out_dir / f"frame_{i:04d}.jpg"
        # -ss before -i = fast (keyframe) seek; -frames:v 1 = single frame
        _run(["ffmpeg", "-y", "-ss", f"{t:.2f}", "-i", video_path,
              "-frames:v", "1", "-vf", f"scale={scale_w}:-1",
              str(path), "-loglevel", "error"])
        if path.exists() and path.stat().st_size > 0:
            frames.append({"index": len(frames), "time": round(t, 2),
                           "path": str(path)})
    return frames
