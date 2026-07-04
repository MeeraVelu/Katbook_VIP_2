"""Settings + profiles: every profile flattens to a complete config, env overrides
win, and the EMBED_DIM/EMBED_MODEL mismatch fails fast."""

from __future__ import annotations

import pytest

from pipeline.config import load_config
from pipeline.settings import PROFILES, Settings

REQUIRED_KEYS = {
    "WHISPER_MODEL",
    "CLIP_MODEL",
    "YOLO_MODEL",
    "BLIP2_MODEL",
    "LLM_MODEL",
    "EMBED_MODEL",
    "EMBED_DIM",
    "TAGGING_BACKEND",
    "MAX_FRAMES_VOICE",
    "MAX_FRAMES_SILENT",
    "SCENE_LABELS",
    "REALWORLD_SCENES",
    "TEXTY_SCENES",
}


@pytest.mark.parametrize("profile", list(PROFILES))
def test_every_profile_is_complete(profile):
    cfg = load_config({"PROFILE": profile})
    missing = REQUIRED_KEYS - set(cfg)
    assert not missing, f"{profile} missing {missing}"


def test_production_profile_uses_bge_m3_and_vllm():
    cfg = load_config({"PROFILE": "production"})
    assert cfg["EMBED_MODEL"] == "BAAI/bge-m3"
    assert cfg["EMBED_DIM"] == 1024
    assert cfg["TAGGING_BACKEND"] == "vllm"
    assert cfg["RESIDENT_VISUAL_STACK"] is True


def test_smoke_profile_uses_stub_tagger():
    cfg = load_config({"PROFILE": "smoke"})
    assert cfg["TAGGING_BACKEND"] == "stub"
    assert cfg["EMBED_DIM"] == 384


def test_caller_override_wins_over_profile():
    cfg = load_config({"PROFILE": "smoke", "MAX_SEGMENTS": 3})
    assert cfg["MAX_SEGMENTS"] == 3


def test_embed_dim_mismatch_fails_fast(monkeypatch):
    monkeypatch.setenv("KVIP_EMBED_MODEL", "BAAI/bge-m3")
    monkeypatch.setenv("KVIP_EMBED_DIM", "384")  # wrong for bge-m3
    with pytest.raises(ValueError):
        Settings()


def test_unknown_profile_rejected():
    with pytest.raises(ValueError):
        load_config({"PROFILE": "does-not-exist"})
