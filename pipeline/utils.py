"""
utils.py — cross-cutting helpers: structured logging, timing, GPU memory
discipline, and lightweight checkpointing.

The GPU helpers are the heart of the "load each model one-by-one, never all at
once" requirement. `managed_model()` guarantees a model is freed and the CUDA
cache cleared the instant a stage finishes -- even if it raises -- so a single
16 GB T4 never accumulates two big models.
"""

from __future__ import annotations

import gc
import json
import time
from contextlib import contextmanager
from datetime import UTC
from pathlib import Path

# --------------------------------------------------------------------------- #
# Logging — delegates to the structured (JSON) logger in logging_config, so every
# existing `log(...)` call site keeps working but now emits a structured record
# carrying the bound context (request_id / video_id / stage). No behavior change
# for callers.
# --------------------------------------------------------------------------- #
_T0 = time.time()

_LEVELS = {"DEBUG": 10, "INFO": 20, "WARN": 30, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}


def log(msg: str, level: str = "INFO") -> None:
    from .logging_config import get_logger

    get_logger("pipeline.pipeline").log(_LEVELS.get(level.upper(), 20), msg)


# --------------------------------------------------------------------------- #
# Torch is imported lazily so this module imports on a CPU-only box (tests/CI).
# --------------------------------------------------------------------------- #
def _torch():
    import torch  # noqa: PLC0415

    return torch


def vram_mb() -> float:
    try:
        t = _torch()
        if t.cuda.is_available():
            return t.cuda.memory_allocated() / 1e6
    except Exception:
        pass
    return 0.0


def free_vram(*objs) -> None:
    """Delete refs, run GC, empty the CUDA cache. Call after every heavy model."""
    for o in objs:
        try:
            del o
        except Exception:
            pass
    gc.collect()
    try:
        t = _torch()
        if t.cuda.is_available():
            t.cuda.empty_cache()
            t.cuda.ipc_collect()
    except Exception:
        pass


@contextmanager
def managed_model(name: str):
    """
    Context manager enforcing the one-model-at-a-time discipline.

        with managed_model("CLIP") as keep:
            model = load_clip()
            keep(model, processor)      # register for guaranteed cleanup
            ... use model ...
        # model + processor are deleted and VRAM is cleared here, even on error.

    Logs VRAM before/after so you can SEE memory return to baseline between
    stages -- the proof that nothing is leaking across models.
    """
    before = vram_mb()
    log(f"{name}: loading  (VRAM {before:.0f} MB)")
    registered: list = []

    def keep(*objs):
        registered.extend(objs)
        return objs[0] if len(objs) == 1 else objs

    t0 = time.time()
    try:
        yield keep
    finally:
        free_vram(*registered)
        after = vram_mb()
        log(f"{name}: freed in {time.time() - t0:5.1f}s (VRAM {before:.0f} -> {after:.0f} MB)")


@contextmanager
def timer(payload_timings: dict, key: str):
    """Record wall-clock seconds for a stage into payload['stage_timings']."""
    t0 = time.time()
    try:
        yield
    finally:
        payload_timings[key] = round(time.time() - t0, 2)


# --------------------------------------------------------------------------- #
# Checkpointing — survive Kaggle session resets without redoing expensive work.
# We cache the single most expensive stage (transcription) keyed by video_id.
# --------------------------------------------------------------------------- #
def checkpoint_path(work_dir: str, subdir: str, video_id: str) -> Path:
    p = Path(work_dir) / subdir
    p.mkdir(parents=True, exist_ok=True)
    return p / f"{video_id}.json"


def load_checkpoint(work_dir: str, subdir: str, video_id: str) -> dict | None:
    p = checkpoint_path(work_dir, subdir, video_id)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            return None
    return None


def save_checkpoint(work_dir: str, subdir: str, video_id: str, data: dict) -> None:
    p = checkpoint_path(work_dir, subdir, video_id)
    try:
        p.write_text(json.dumps(data, default=str))
    except Exception as e:  # checkpoint failure must never crash the pipeline
        log(f"checkpoint write failed ({e})", "WARN")


def gpu_banner() -> str:
    """One-line GPU summary for the run header."""
    try:
        t = _torch()
        if t.cuda.is_available():
            names = [t.cuda.get_device_name(i) for i in range(t.cuda.device_count())]
            return f"CUDA on: {t.cuda.device_count()}x {names[0]}"
        return "CUDA off: running on CPU (slow — use Kaggle T4 x2)"
    except Exception:
        return "torch not importable yet"


def _gpu_name() -> str | None:
    try:
        t = _torch()
        if t.cuda.is_available():
            return t.cuda.get_device_name(0)
    except Exception:
        pass
    return None


def capture_runtime(cfg: dict | None = None) -> dict:
    """Provenance of WHERE this video was actually processed.

    Captured on the processing machine (Kaggle) at processing time and stored in
    the DB, so downstream tools (e.g. the laptop result-sync) report the true
    processing environment instead of re-stamping themselves. This is why the
    os/python in a result reflect Kaggle's Linux + Python, not your Windows box.
    """
    import platform
    from datetime import datetime

    rt = {
        "os": f"{platform.system()} {platform.release()}",
        "python": platform.python_version(),
        "gpu": _gpu_name(),
        "processed_on": datetime.now(UTC).isoformat(),
    }
    if cfg:
        rt["profile"] = cfg.get("PROFILE")
    try:
        from . import __version__ as _v

        rt["package_version"] = _v
    except Exception:
        pass
    return rt
