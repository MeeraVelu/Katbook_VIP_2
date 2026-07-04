"""Router decision: voice vs silent path (the pipeline's first real decision)."""

from __future__ import annotations

from pipeline.config import load_config
from pipeline.router import SILENT, VOICE, decide

CFG = load_config({"PROFILE": "smoke"})


def test_no_speech_routes_silent():
    r = decide(has_speech=False, mean_rms_db=-99.0, speech_sec=0.0, cfg=CFG)
    assert r.path == SILENT
    assert r.force_captions is True
    assert r.ocr_all_frames is True
    assert r.max_frames == CFG["MAX_FRAMES_SILENT"]


def test_tiny_speech_below_threshold_routes_silent():
    # speech present but under MIN_SPEECH_SEC -> still silent path
    r = decide(has_speech=True, mean_rms_db=-30.0, speech_sec=1.0, cfg=CFG)
    assert r.path == SILENT


def test_narration_routes_voice():
    r = decide(has_speech=True, mean_rms_db=-25.0, speech_sec=42.0, cfg=CFG)
    assert r.path == VOICE
    assert r.force_captions is False
    assert r.ocr_all_frames is False
    assert r.max_frames == CFG["MAX_FRAMES_VOICE"]


def test_min_speech_boundary():
    # exactly at the threshold counts as voice (strict < is silent)
    r = decide(has_speech=True, mean_rms_db=-25.0, speech_sec=CFG["MIN_SPEECH_SEC"], cfg=CFG)
    assert r.path == VOICE
