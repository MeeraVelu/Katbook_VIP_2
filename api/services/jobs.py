"""
api/services/jobs.py — job lifecycle helpers, shared by the API (reads) and the
worker (writes). A ``job`` row is the user-visible unit of work behind a video;
the worker advances ``state``/``current_stage``/``stage_timings`` so
``GET /api/v1/jobs/{id}`` reflects live progress.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.services.models import Job


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def create_job(session: Session, video_id: uuid.UUID) -> Job:
    job = Job(job_id=uuid.uuid4(), video_id=video_id, state="queued", attempts=0)
    session.add(job)
    session.flush()
    return job


def get_job(session: Session, job_id: uuid.UUID) -> Job | None:
    return session.get(Job, job_id)


def latest_job_for_video(session: Session, video_id: uuid.UUID) -> Job | None:
    return session.execute(
        select(Job).where(Job.video_id == video_id).order_by(Job.enqueued_at.desc()).limit(1)
    ).scalar_one_or_none()


def mark_started(session: Session, job_id: uuid.UUID) -> None:
    job = session.get(Job, job_id)
    if job:
        job.state = "processing"
        job.started_at = _now()
        job.attempts += 1
        job.updated_at = _now()


def mark_stage(
    session: Session, job_id: uuid.UUID, stage: str, stage_timings: dict | None = None
) -> None:
    job = session.get(Job, job_id)
    if job:
        job.state = "processing"
        job.current_stage = stage
        if stage_timings is not None:
            job.stage_timings = stage_timings
        job.updated_at = _now()


def mark_done(session: Session, job_id: uuid.UUID, stage_timings: dict | None = None) -> None:
    job = session.get(Job, job_id)
    if job:
        job.state = "done"
        job.current_stage = "done"
        job.finished_at = _now()
        if stage_timings is not None:
            job.stage_timings = stage_timings
        job.error = None
        job.updated_at = _now()


def mark_failed(session: Session, job_id: uuid.UUID, error: str) -> None:
    job = session.get(Job, job_id)
    if job:
        job.state = "failed"
        job.finished_at = _now()
        job.error = error[:2000]
        job.updated_at = _now()


def elapsed_seconds(job: Job) -> float | None:
    if not job.started_at:
        return None
    end = job.finished_at or _now()
    start = job.started_at
    # tolerate naive timestamps from some drivers
    if start.tzinfo is None:
        start = start.replace(tzinfo=dt.UTC)
    if end.tzinfo is None:
        end = end.replace(tzinfo=dt.UTC)
    return round((end - start).total_seconds(), 1)
