"""
worker/celery_app.py — Celery application for the GPU pipeline.

Design:
  * **One task per GPU.** ``worker_concurrency=1`` (env-overridable) +
    ``worker_prefetch_multiplier=1`` so a single worker never runs two videos at
    once (models are large). Scaling to a second RTX 5090 later = start another
    worker container with ``CUDA_VISIBLE_DEVICES=1`` on the same ``gpu`` queue.
  * **acks_late + reject_on_worker_lost.** A video is re-queued if the worker dies
    mid-task, and the pipeline's transcript checkpoint means it resumes cheaply.
"""

from __future__ import annotations

import os

from celery import Celery

from api.settings import get_api_settings

_s = get_api_settings()

celery_app = Celery(
    "katbook_worker",
    broker=_s.redis_url,
    backend=_s.redis_url,
    include=["worker.tasks"],
)

celery_app.conf.update(
    task_default_queue="gpu",
    task_routes={
        "worker.tasks.process_video": {"queue": "gpu"},
        "worker.tasks.process_batch": {"queue": "gpu"},
    },
    worker_concurrency=int(os.environ.get("WORKER_CONCURRENCY", "1")),
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_track_started=True,
    task_time_limit=int(os.environ.get("TASK_TIME_LIMIT", "7200")),  # 2h hard
    task_soft_time_limit=int(os.environ.get("TASK_SOFT_TIME_LIMIT", "6900")),
    result_expires=int(os.environ.get("RESULT_EXPIRES", "86400")),
    broker_connection_retry_on_startup=True,
    worker_hijack_root_logger=False,
)

# start the GPU heartbeat + configure logging when the worker process boots
from worker import heartbeat  # noqa: E402,F401  (registers Celery signals)
