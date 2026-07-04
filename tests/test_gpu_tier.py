"""GPU-tier detection + the settings precedence it layers into. CPU-only:
torch is never imported — the device probe is monkeypatched."""
from __future__ import annotations

import pytest

from pipeline import gpu_profile as gp
from pipeline.config import load_config
from pipeline.gpu_profile import TIERS, classify, tier_config


# --- pure classification --------------------------------------------------- #
@pytest.mark.parametrize(
    "name,vram,cap,expected",
    [
        ("NVIDIA A100-SXM4-80GB", 80.0, (8, 0), "datacenter"),
        ("NVIDIA H100 80GB HBM3", 80.0, (9, 0), "datacenter"),
        ("NVIDIA GeForce RTX 5090", 31.8, (12, 0), "rtx5090"),
        ("Blackwell Device", 31.0, (12, 0), "rtx5090"),
        ("NVIDIA GeForce RTX 4090", 24.0, (8, 9), "rtx_high"),
        ("NVIDIA GeForce RTX 4080", 16.0, (8, 9), "t4_16gb"),
        ("Tesla T4", 15.8, (7, 5), "t4_16gb"),
        (None, None, None, "cpu"),
    ],
)
def test_classify(name, vram, cap, expected):
    assert classify(name, vram, cap) == expected


# --- detection (probe mocked) ---------------------------------------------- #
def _mock_probe(monkeypatch, cuda, name, vram, cap):
    monkeypatch.setattr(gp, "_probe", lambda: (cuda, name, vram, cap))
    gp.reset_cache()


def test_detect_cpu_when_no_cuda(monkeypatch):
    _mock_probe(monkeypatch, False, None, None, None)
    p = gp.detect()
    assert p.tier == "cpu" and p.cuda is False and p.source == "cpu"


def test_detect_rtx5090(monkeypatch):
    _mock_probe(monkeypatch, True, "NVIDIA GeForce RTX 5090", 31.8, (12, 0))
    p = gp.detect()
    assert p.tier == "rtx5090" and p.source == "auto"
    assert p.vram_gb == 31.8 and p.capability == "sm_120"


def test_gpu_profile_env_override_wins(monkeypatch):
    # a 5090 is present but the operator forces t4_16gb
    monkeypatch.setenv("GPU_PROFILE", "t4_16gb")
    _mock_probe(monkeypatch, True, "NVIDIA GeForce RTX 5090", 31.8, (12, 0))
    p = gp.detect()
    assert p.tier == "t4_16gb" and p.source == "override"


def test_gpu_profile_invalid_override_raises(monkeypatch):
    monkeypatch.setenv("GPU_PROFILE", "banana")
    _mock_probe(monkeypatch, False, None, None, None)
    with pytest.raises(ValueError):
        gp.detect()


# --- the hard rule: BGE-M3 1024-d on EVERY tier ---------------------------- #
@pytest.mark.parametrize("tier", TIERS)
def test_every_tier_is_1024d_bge_m3(tier):
    knobs = tier_config(tier)
    assert knobs["EMBED_DIM"] == 1024
    assert knobs["EMBED_MODEL"] == "BAAI/bge-m3"
    assert knobs["GPU_TIER"] == tier


# --- precedence layered into load_config ----------------------------------- #
def test_apply_tier_sets_worker_knobs(monkeypatch):
    _mock_probe(monkeypatch, True, "NVIDIA GeForce RTX 5090", 31.8, (12, 0))
    cfg = load_config(apply_tier=True)
    assert cfg["GPU_TIER"] == "rtx5090"
    assert cfg["WHISPER_MODEL"] == "large-v3"
    assert cfg["YOLO_MODEL"] == "yolo11x.pt"
    assert cfg["OCR_LANGS"] == ["en", "ta", "hi"]
    assert cfg["RESIDENT_VISUAL_STACK"] is True
    assert cfg["EMBED_DIM"] == 1024


def test_explicit_env_beats_tier(monkeypatch):
    _mock_probe(monkeypatch, True, "NVIDIA GeForce RTX 5090", 31.8, (12, 0))
    monkeypatch.setenv("KVIP_WHISPER_MODEL", "custom-whisper")
    cfg = load_config(apply_tier=True)
    assert cfg["WHISPER_MODEL"] == "custom-whisper"  # env > tier
    assert cfg["GPU_TIER"] == "rtx5090"


def test_tier_beats_profile(monkeypatch):
    # cpu tier forces 1024-d even under the smoke profile (whose default is 384)
    _mock_probe(monkeypatch, False, None, None, None)
    cfg = load_config({"PROFILE": "smoke"}, apply_tier=True)
    assert cfg["GPU_TIER"] == "cpu"
    assert cfg["EMBED_DIM"] == 1024
    assert cfg["EMBED_MODEL"] == "BAAI/bge-m3"


def test_without_apply_tier_profile_unchanged(monkeypatch):
    # default load_config (batch CLI / smoke) is unaffected by the tier layer
    _mock_probe(monkeypatch, True, "NVIDIA GeForce RTX 5090", 31.8, (12, 0))
    cfg = load_config({"PROFILE": "smoke"})
    assert "GPU_TIER" not in cfg
    assert cfg["EMBED_DIM"] == 384  # smoke profile default preserved


def test_worker_config_asserts_1024(monkeypatch):
    from worker.tasks import _load_worker_config

    # force an embedder mismatch via explicit env (consistent per Settings), which
    # beats the tier's 1024 -> the worker must fail fast.
    _mock_probe(monkeypatch, False, None, None, None)
    monkeypatch.setenv("KVIP_EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
    monkeypatch.setenv("KVIP_EMBED_DIM", "384")
    with pytest.raises(RuntimeError, match="vector\\(1024\\)"):
        _load_worker_config()


def test_worker_config_ok_on_default(monkeypatch):
    _mock_probe(monkeypatch, True, "NVIDIA GeForce RTX 5090", 31.8, (12, 0))
    from worker.tasks import _load_worker_config

    cfg = _load_worker_config()
    assert cfg["EMBED_DIM"] == 1024 and cfg["GPU_TIER"] == "rtx5090"
