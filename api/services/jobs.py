"""
api/services/jobs.py — job lifecycle helpers, shared by the API (reads) and the
worker (writes). A ``job`` row is the user-visible unit of work behind a video;
the worker advances ``state``/``current_stage``/``stage_timings`` so
``GET /api/v1/jobs/{id}`` reflects live progress.
"""

from __future__ import annotations

import datetime as dt
import os
import uuid
from collections import Counter, defaultdict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.services.models import Job, Segment, Video


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def create_job(session: Session, video_id: uuid.UUID, video_filename: str | None = None) -> Job:
    job = Job(
        job_id=uuid.uuid4(),
        video_id=video_id,
        video_filename=video_filename,
        state="queued",
        attempts=0,
    )
    session.add(job)
    session.flush()
    return job


def get_job(session: Session, job_id: uuid.UUID) -> Job | None:
    return session.get(Job, job_id)


def latest_job_for_video(session: Session, video_id: uuid.UUID) -> Job | None:
    return session.execute(
        select(Job).where(Job.video_id == video_id).order_by(Job.enqueued_at.desc()).limit(1)
    ).scalar_one_or_none()


def mark_started(session: Session, job_id: uuid.UUID, profile: str | None = None) -> None:
    job = session.get(Job, job_id)
    if job:
        job.state = "processing"
        job.started_at = _now()
        job.attempts += 1
        job.progress_pct = 0
        if profile is not None:
            job.profile = profile
        job.updated_at = _now()


def mark_stage(
    session: Session,
    job_id: uuid.UUID,
    stage: str,
    stage_timings: dict | None = None,
    progress_pct: int | None = None,
) -> None:
    job = session.get(Job, job_id)
    if job:
        job.state = "processing"
        job.current_stage = stage
        if stage_timings is not None:
            job.stage_timings = stage_timings
        if progress_pct is not None:
            job.progress_pct = progress_pct
        job.updated_at = _now()


def mark_done(session: Session, job_id: uuid.UUID, stage_timings: dict | None = None) -> None:
    job = session.get(Job, job_id)
    if job:
        job.state = "done"
        job.current_stage = "done"
        job.progress_pct = 100
        job.finished_at = _now()
        if stage_timings is not None:
            job.stage_timings = stage_timings
        job.error = None
        job.updated_at = _now()


def mark_failed(session: Session, job_id: uuid.UUID, error: str) -> None:
    job = session.get(Job, job_id)
    if job:
        job.state = "failed"
        # best-effort: the last stage that reported completion before the
        # exception — not necessarily the stage that raised it, but close.
        job.error_stage = job.current_stage
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


def list_active_jobs(session: Session) -> list[tuple[Job, str | None]]:
    """(Job, video filename) pairs currently ``processing``. Normally at most
    one — the worker runs ``concurrency=1`` (one video per GPU) — but this
    returns a list so a multi-GPU-worker setup (docs/DEPLOYMENT.md) is
    represented correctly. Joins Video so the caller doesn't need a second
    lookup just to know which file is running.

    Only counts a job if it's the MOST RECENT job for its video. A ``force``
    reprocess creates a new job row rather than reusing the old one, so an
    earlier attempt that was interrupted (worker crash/restart, a broker
    that lost its ack) can be left behind stuck at state='processing'
    forever even after a later retry finished successfully — without this
    filter that zombie row would show up as "currently processing" with a
    stale multi-hour elapsed time."""
    latest_per_video = (
        select(Job.video_id, func.max(Job.enqueued_at).label("max_enqueued"))
        .group_by(Job.video_id)
        .subquery()
    )
    rows = session.execute(
        select(Job, Video.source_path)
        .join(Video, Video.video_id == Job.video_id)
        .join(
            latest_per_video,
            (latest_per_video.c.video_id == Job.video_id)
            & (latest_per_video.c.max_enqueued == Job.enqueued_at),
        )
        .where(Job.state == "processing")
        .order_by(Job.started_at.asc())
    ).all()
    return [(job, os.path.basename(path) if path else None) for job, path in rows]


def list_job_history(
    session: Session, *, page: int, page_size: int, status: str | None = None
) -> tuple[list[dict], int]:
    """Completed (``done``) and/or ``failed`` jobs, most recently finished
    first, with the fields the Jobs page's "Processed" tab needs: filename,
    rollup subject, segment count, processing duration, completion time."""
    states = [status] if status in ("done", "failed") else ["done", "failed"]
    base = (
        select(Job, Video.source_path)
        .join(Video, Video.video_id == Job.video_id)
        .where(Job.state.in_(states))
    )
    total = session.execute(select(func.count()).select_from(base.subquery())).scalar_one()

    order_col = func.coalesce(Job.finished_at, Job.updated_at).desc()
    rows = session.execute(
        base.order_by(order_col).offset((page - 1) * page_size).limit(page_size)
    ).all()

    video_ids = [job.video_id for job, _ in rows if job.video_id is not None]
    stats = _batched_segment_stats(session, video_ids)

    items = []
    for job, source_path in rows:
        s = stats.get(job.video_id, {"segment_count": 0, "subject": None})
        items.append(
            {
                "job_id": job.job_id,
                "video_id": job.video_id,
                "video_filename": os.path.basename(source_path) if source_path else None,
                "status": job.state,
                "subject": s["subject"],
                "segment_count": s["segment_count"],
                "processing_duration_sec": elapsed_seconds(job),
                "completed_at": job.finished_at,
                "error": job.error,
            }
        )
    return items, int(total)


def _batched_segment_stats(session: Session, video_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict]:
    """One query for segment_count + most-common subject across many videos —
    avoids an N+1 rollup query per row on the history page."""
    if not video_ids:
        return {}
    rows = session.execute(
        select(Segment.video_id, Segment.subject, func.count())
        .where(Segment.video_id.in_(video_ids))
        .group_by(Segment.video_id, Segment.subject)
    ).all()
    subject_counts: dict[uuid.UUID, Counter] = defaultdict(Counter)
    total_segs: dict[uuid.UUID, int] = defaultdict(int)
    for vid, subject, cnt in rows:
        total_segs[vid] += cnt
        if subject:
            subject_counts[vid][subject] += cnt
    return {
        vid: {
            "segment_count": total_segs[vid],
            "subject": subject_counts[vid].most_common(1)[0][0] if subject_counts[vid] else None,
        }
        for vid in video_ids
    }
