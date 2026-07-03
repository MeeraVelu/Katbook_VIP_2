"""
app/services/queue.py — enqueue work onto Celery/Redis from the API.

The API must stay ML-free, so it never imports ``worker.tasks`` (which pulls in
torch). Instead it holds a bare Celery client and sends the task **by name**; the
worker process owns the implementation. This also means the API image needs only
``celery`` + ``redis``, not the pipeline dependencies.
"""

from __future__ import annotations

import uuid

from celery import Celery

from app.settings import get_api_settings

_app: Celery | None = None


def _client() -> Celery:
    global _app
    if _app is None:
        s = get_api_settings()
        _app = Celery("katbook_api", broker=s.redis_url, backend=s.redis_url)
        _app.conf.task_default_queue = "gpu"
    return _app


def enqueue_video(job_id: uuid.UUID, video_id: uuid.UUID, source_path: str) -> None:
    """Send one video to the GPU worker queue by task name (no worker import)."""
    s = get_api_settings()
    _client().send_task(
        s.celery_task_name,
        args=[str(job_id), str(video_id), source_path],
        queue="gpu",
    )
