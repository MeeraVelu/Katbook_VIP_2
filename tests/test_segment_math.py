"""Segmentation math: min-merge, max-split, cap, full-coverage, and the two
path-specific segmenters — all pure, no models."""

from __future__ import annotations

import numpy as np

from pipeline import segment
from pipeline.config import load_config

CFG = load_config({"PROFILE": "smoke"})


def _durs(segs):
    return [round(s["end"] - s["start"], 2) for s in segs]


def test_merge_min_duration_absorbs_short_tail():
    segs = [{"start": 0, "end": 50}, {"start": 50, "end": 60}]
    merged = segment._merge_min_duration(segs, min_sec=45)
    assert len(merged) == 1 and merged[0]["end"] == 60


def test_split_max_duration_divides_long_block():
    # 300s / 100s max -> 3 equal parts of ~100s (fewest equal parts <= max_sec)
    segs = [{"start": 0, "end": 300}]
    out = segment._split_max_duration(segs, max_sec=100, min_sec=45)
    assert len(out) == 3
    assert all((s["end"] - s["start"]) <= 105 for s in out)
    assert out[0]["start"] == 0 and out[-1]["end"] == 300


def test_cap_segments_respects_limit():
    segs = [{"start": i * 10, "end": i * 10 + 10} for i in range(20)]
    out = segment._cap_segments(segs, max_segments=5)
    assert len(out) <= 5
    assert out[0]["start"] == 0 and out[-1]["end"] == 200


def test_ensure_full_coverage_extends_to_duration():
    segs = [{"start": 0, "end": 40}]
    out = segment._ensure_full_coverage(segs, duration=120, max_sec=120, min_sec=45)
    assert out[-1]["end"] == 120


def test_segment_voiced_covers_full_duration():
    windows = [{"start": i * 30, "end": i * 30 + 30, "text": f"w{i}"} for i in range(6)]
    # alternating embeddings force a boundary or two
    emb = np.array([[1.0, 0.0] if i % 2 == 0 else [0.0, 1.0] for i in range(6)])
    segs = segment.segment_voiced(windows, emb, duration=180, cfg=CFG)
    assert segs[0]["start"] == 0
    assert abs(segs[-1]["end"] - 180) < 1.0
    assert len(segs) <= CFG["MAX_SEGMENTS"]


def test_segment_silent_groups_by_scene():
    frames = [
        {"time": 0, "scene": "slide presentation"},
        {"time": 60, "scene": "slide presentation"},
        {"time": 120, "scene": "diagram explanation"},
    ]
    segs = segment.segment_silent(frames, duration=180, cfg=CFG)
    assert segs[0]["start"] == 0
    assert abs(segs[-1]["end"] - 180) < 1.0


def test_attach_signals_populates_text_and_visuals():
    segs = [{"start": 0, "end": 60}]
    transcript = [{"start": 5, "end": 10, "text": "hello world"}]
    frames = [
        {
            "time": 3,
            "scene": "slide presentation",
            "objects": ["book"],
            "ocr": "TITLE",
            "caption": "a slide",
        }
    ]
    out = segment.attach_signals(segs, transcript, frames)
    assert out[0]["text"] == "hello world"
    assert out[0]["scenes"] == ["slide presentation"]
    assert out[0]["objects"] == ["book"]
    assert "TITLE" in out[0]["ocr"]
