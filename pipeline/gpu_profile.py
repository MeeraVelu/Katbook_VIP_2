"""
gpu_profile.py — detect the worker's GPU tier and the model knobs that suit it.

The tier is derived once per process from ``torch.cuda`` (device name + total
VRAM + compute capability), or forced by the ``GPU_PROFILE`` env var. It adjusts
ONLY worker-loaded knobs (Whisper / CLIP / YOLO / BLIP-2 / OCR / frame budgets /
RESIDENT_VISUAL_STACK / the in-process-fallback LLM). vLLM stays a compose-level
service; the tier never turns it on/off.

HARD RULE: the segment embedder is **BAAI/bge-m3 (1024-d) on EVERY tier**, because
the database column is ``vector(1024)``. ``tier_config`` enforces this and the
worker asserts it at startup.

Layering (in config.load_config, precedence high→low):
    explicit env / caller overrides  >  GPU_PROFILE tier knobs  >  profile defaults
Tier layering is opt-in (``load_config(apply_tier=True)``) — the worker enables it;
the batch CLI / smoke test keep the plain profile behavior.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from .logging_config import get_logger

TIERS = ("cpu", "t4_16gb", "rtx_high", "rtx5090", "datacenter")

# The one invariant that must hold on every tier (DB is vector(1024)).
EMBED_MODEL = "BAAI/bge-m3"
EMBED_DIM = 1024

# Datacenter accelerators recognised by name.
_DATACENTER_MARKERS = ("a100", "a800", "h100", "h800", "h200", "b200", "gh200")


@dataclass(frozen=True)
class GpuProfile:
    tier: str
    device: str | None
    vram_gb: float | None
    capability: str | None
    cuda: bool
    source: str  # "override" | "auto" | "cpu"

    def as_dict(self) -> dict[str, Any]:
        return {
            "tier": self.tier,
            "device": self.device,
            "vram_gb": self.vram_gb,
            "capability": self.capability,
            "cuda": self.cuda,
            "source": self.source,
        }


def _probe() -> tuple[bool, str | None, float | None, tuple[int, int] | None]:
    """Return (cuda_available, device_name, total_vram_gb, capability)."""
    try:
        import torch

        if not torch.cuda.is_available():
            return (False, None, None, None)
        props = torch.cuda.get_device_properties(0)
        cap = torch.cuda.get_device_capability(0)
        return (True, torch.cuda.get_device_name(0), props.total_memory / 1e9, cap)
    except Exception:
        return (False, None, None, None)


def classify(name: str | None, vram_gb: float | None, capability: tuple[int, int] | None) -> str:
    """Map a device (name/VRAM/capability) to a tier. Pure — unit-testable."""
    n = (name or "").lower()
    if any(m in n for m in _DATACENTER_MARKERS):
        return "datacenter"
    # Blackwell consumer (RTX 5090 = sm_120, 32 GB)
    if "5090" in n or (capability is not None and capability[0] >= 12):
        return "rtx5090"
    if vram_gb is None:
        return "cpu"
    if vram_gb >= 30:
        return "rtx5090"
    if vram_gb >= 20:
        return "rtx_high"
    return "t4_16gb"


@lru_cache(maxsize=1)
def detect() -> GpuProfile:
    """Detect the tier once per process (GPU_PROFILE env always wins)."""
    override = os.environ.get("GPU_PROFILE")
    cuda, name, vram, cap = _probe()
    capstr = f"sm_{cap[0]}{cap[1]}" if cap else None
    vram_r = round(vram, 1) if vram is not None else None

    if override:
        ov = override.strip().lower()
        if ov not in TIERS:
            raise ValueError(f"GPU_PROFILE={override!r} is not a valid tier {TIERS}")
        return GpuProfile(ov, name, vram_r, capstr, cuda, "override")
    if not cuda:
        return GpuProfile("cpu", None, None, None, False, "cpu")
    return GpuProfile(classify(name, vram, cap), name, vram_r, capstr, cuda, "auto")


def reset_cache() -> None:
    """Clear the per-process cache (used by tests that vary env / torch)."""
    detect.cache_clear()


def detect_tier() -> str:
    return detect().tier


# --------------------------------------------------------------------------- #
# Per-tier worker knobs. NOTE: no vLLM toggles here (compose-level); LLM_MODEL is
# the in-process fallback model only.
# --------------------------------------------------------------------------- #
TIER_KNOBS: dict[str, dict[str, Any]] = {
    "cpu": {
        "WHISPER_MODEL": "tiny",
        "WHISPER_COMPUTE_TYPE": "int8",
        "WHISPER_BEAM": 1,
        "CLIP_MODEL": "openai/clip-vit-base-patch32",
        "YOLO_ENABLED": False,
        "YOLO_MODEL": "yolov8n.pt",
        "BLIP2_ENABLED": False,
        "BLIP2_MODEL": "Salesforce/blip2-opt-2.7b",
        "BLIP2_DTYPE": "float32",
        "OCR_LANGS": ["en"],
        "MAX_FRAMES_VOICE": 4,
        "MAX_FRAMES_SILENT": 6,
        "CAPTION_FRAMES": 0,
        "RESIDENT_VISUAL_STACK": False,
        "LLM_MODEL": "Qwen/Qwen2.5-0.5B-Instruct",
    },
    "t4_16gb": {
        "WHISPER_MODEL": "medium",
        "WHISPER_COMPUTE_TYPE": "int8_float16",
        "WHISPER_BEAM": 1,
        "CLIP_MODEL": "openai/clip-vit-base-patch32",
        "YOLO_ENABLED": True,
        "YOLO_MODEL": "yolov8n.pt",
        "BLIP2_ENABLED": True,
        "BLIP2_MODEL": "Salesforce/blip2-opt-2.7b",
        "BLIP2_DTYPE": "float16",
        "OCR_LANGS": ["en"],
        "MAX_FRAMES_VOICE": 12,
        "MAX_FRAMES_SILENT": 24,
        "CAPTION_FRAMES": 6,
        "RESIDENT_VISUAL_STACK": False,
        "LLM_MODEL": "Qwen/Qwen2.5-7B-Instruct",
    },
    "rtx_high": {
        "WHISPER_MODEL": "large-v3",
        "WHISPER_COMPUTE_TYPE": "float16",
        "WHISPER_BEAM": 3,
        "CLIP_MODEL": "openai/clip-vit-large-patch14",
        "YOLO_ENABLED": True,
        "YOLO_MODEL": "yolo11l.pt",
        "BLIP2_ENABLED": True,
        "BLIP2_MODEL": "Salesforce/blip2-opt-2.7b",
        "BLIP2_DTYPE": "float16",
        "OCR_LANGS": ["en", "ta", "hi"],
        "MAX_FRAMES_VOICE": 16,
        "MAX_FRAMES_SILENT": 32,
        "CAPTION_FRAMES": 10,
        "RESIDENT_VISUAL_STACK": True,
        "LLM_MODEL": "Qwen/Qwen2.5-7B-Instruct",
    },
    "rtx5090": {
        "WHISPER_MODEL": "large-v3",
        "WHISPER_COMPUTE_TYPE": "float16",
        "WHISPER_BEAM": 3,
        "CLIP_MODEL": "openai/clip-vit-large-patch14",
        "YOLO_ENABLED": True,
        "YOLO_MODEL": "yolo11x.pt",
        "BLIP2_ENABLED": True,
        "BLIP2_MODEL": "Salesforce/blip2-opt-2.7b",
        "BLIP2_DTYPE": "float16",
        "OCR_LANGS": ["en", "ta", "hi"],
        "MAX_FRAMES_VOICE": 18,
        "MAX_FRAMES_SILENT": 40,
        "CAPTION_FRAMES": 12,
        "RESIDENT_VISUAL_STACK": True,
        "LLM_MODEL": "Qwen/Qwen2.5-7B-Instruct",
    },
    "datacenter": {
        "WHISPER_MODEL": "large-v3",
        "WHISPER_COMPUTE_TYPE": "float16",
        "WHISPER_BEAM": 5,
        "CLIP_MODEL": "openai/clip-vit-large-patch14",
        "YOLO_ENABLED": True,
        "YOLO_MODEL": "yolo11x.pt",
        "BLIP2_ENABLED": True,
        "BLIP2_MODEL": "Salesforce/blip2-opt-6.7b",
        "BLIP2_DTYPE": "float16",
        "OCR_LANGS": ["en", "ta", "hi"],
        "MAX_FRAMES_VOICE": 24,
        "MAX_FRAMES_SILENT": 48,
        "CAPTION_FRAMES": 16,
        "RESIDENT_VISUAL_STACK": True,
        "LLM_MODEL": "Qwen/Qwen2.5-14B-Instruct",
    },
}


def tier_config(tier: str) -> dict[str, Any]:
    """Worker knobs for a tier, with the embedder invariant enforced."""
    if tier not in TIER_KNOBS:
        raise ValueError(f"Unknown tier {tier!r}; choose {TIERS}")
    knobs = dict(TIER_KNOBS[tier])
    # HARD RULE: BGE-M3 1024-d on every tier (DB column is vector(1024)).
    knobs["EMBED_MODEL"] = EMBED_MODEL
    knobs["EMBED_DIM"] = EMBED_DIM
    knobs["GPU_TIER"] = tier
    return knobs


def log_startup(cfg: dict[str, Any] | None = None) -> GpuProfile:
    """Log the resolved tier + device + VRAM at worker startup and return it."""
    p = detect()
    get_logger("pipeline.gpu").info(
        f"GPU tier = {p.tier} (source={p.source})",
        extra={
            "tier": p.tier,
            "device": p.device,
            "vram_gb": p.vram_gb,
            "capability": p.capability,
            "cuda": p.cuda,
        },
    )
    return p
