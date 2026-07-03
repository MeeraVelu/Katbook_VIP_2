#!/usr/bin/env python
"""
make_test_video.py — generate a small self-contained test clip with ffmpeg.

Used by the CPU smoke test (no GPU, no external assets): a 10-second 320x240
pattern video (ffmpeg `testsrc`, which draws a moving counter/text) plus a silent
mono 16 kHz audio track (so audio extraction + the speech gate run and route the
clip down the SILENT path). Prints the output path.

    python scripts/make_test_video.py [OUTPUT.mp4]
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def make_test_video(out_path: str, seconds: int = 10) -> str:
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"testsrc=duration={seconds}:size=320x240:rate=10",
        "-f",
        "lavfi",
        "-i",
        "anullsrc=r=16000:cl=mono",
        "-t",
        str(seconds),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        str(out),
        "-loglevel",
        "error",
    ]
    subprocess.run(cmd, check=True)
    if not out.exists() or out.stat().st_size == 0:
        raise RuntimeError("ffmpeg produced no output (is ffmpeg installed?)")
    return str(out)


if __name__ == "__main__":
    dest = sys.argv[1] if len(sys.argv) > 1 else "test_data/smoke_clip.mp4"
    print(make_test_video(dest))
