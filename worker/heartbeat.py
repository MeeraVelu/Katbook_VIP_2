"""
worker/heartbeat.py — publish a GPU-visibility heartbeat to Redis.

The API's ``/ready`` probe can't see the GPU (it lives in the worker), so the
worker writes a heartbeat key every ``HEARTBEAT_INTERVAL`` seconds carrying the
current timestamp and GPU name. A stale/absent heartbeat makes the API report
not-ready. Also configures structured logging for the worker process.
"""

from __future__ import annotations

import json
import os
import threading
import time

from celery.signals import worker_process_init, worker_ready

from pipeline.logging_config import configure_logging, get_logger

HEARTBEAT_KEY = "katbook:worker:heartbeat"
HEARTBEAT_INFO_KEY = "katbook:worker:info"
HEARTBEAT_INTERVAL = int(os.environ.get("HEARTBEAT_INTERVAL", "30"))

_log = get_logger("worker.heartbeat")
_thread_started = False


def _gpu_info() -> dict:
    try:
        import torch

        if torch.cuda.is_available():
            cap = torch.cuda.get_device_capability(0)
            return {
                "cuda": True,
                "device": torch.cuda.get_device_name(0),
                "capability": f"sm_{cap[0]}{cap[1]}",
                "count": torch.cuda.device_count(),
            }
    except Exception as e:  # torch missing / no GPU
        return {"cuda": False, "error": str(e)[:120]}
    return {"cuda": False}


def _redis():
    import redis

    from api.settings import get_api_settings

    return redis.Redis.from_url(get_api_settings().redis_url)


def _beat_loop() -> None:
    info = _gpu_info()
    _log.info("worker GPU heartbeat starting", extra=info)
    try:
        r = _redis()
    except Exception as e:
        _log.warning(f"heartbeat: redis unavailable ({str(e)[:80]})")
        return
    while True:
        try:
            r.set(HEARTBEAT_KEY, str(time.time()), ex=HEARTBEAT_INTERVAL * 3)
            r.set(HEARTBEAT_INFO_KEY, json.dumps(info), ex=HEARTBEAT_INTERVAL * 3)
        except Exception as e:
            _log.warning(f"heartbeat write failed ({str(e)[:80]})")
        time.sleep(HEARTBEAT_INTERVAL)


def _start_beat() -> None:
    global _thread_started
    if _thread_started:
        return
    _thread_started = True
    threading.Thread(target=_beat_loop, name="gpu-heartbeat", daemon=True).start()


@worker_process_init.connect
def _on_process_init(**_kwargs) -> None:
    configure_logging()
    _start_beat()


@worker_ready.connect
def _on_ready(**_kwargs) -> None:
    # solo pool doesn't fork, so worker_process_init may not fire — cover both.
    configure_logging()
    _start_beat()
