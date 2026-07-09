"""api/routers/jobs.py — job status (live stage + timings), the currently
active job(s), and completed/failed job history."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.deps import db_session, require_api_key, settings_dep
from api.schemas.common import Page
from api.schemas.jobs import ActiveJob, JobHistoryItem, JobStatus
from api.services import jobs as svc
from api.services.videos import VideoError
from api.settings import APISettings

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"], dependencies=[Depends(require_api_key)])


def _job_status(job) -> JobStatus:
    return JobStatus(
        job_id=job.job_id,
        video_id=job.video_id,
        state=job.state,
        current_stage=job.current_stage,
        attempts=job.attempts,
        stage_timings=job.stage_timings or {},
        error=job.error,
        enqueued_at=job.enqueued_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        elapsed_sec=svc.elapsed_seconds(job),
    )


# NOTE: /active and /history are registered BEFORE /{job_id} — without that
# ordering FastAPI would try (and fail) to parse "active"/"history" as a UUID,
# the same gotcha as /api/v1/videos/facets vs /{video_id}.
@router.get("/active", response_model=list[ActiveJob])
def get_active_jobs(db: Session = Depends(db_session)) -> list[ActiveJob]:
    """The job(s) currently ``processing`` — powers the Jobs page's
    "Processing" tab. Normally 0 or 1 (worker concurrency=1)."""
    return [
        ActiveJob(**_job_status(job).model_dump(), video_filename=filename)
        for job, filename in svc.list_active_jobs(db)
    ]


@router.get("/history", response_model=Page[JobHistoryItem])
def get_job_history(
    db: Session = Depends(db_session),
    page: int = 1,
    page_size: int | None = None,
    status: str | None = None,  # "done" | "failed" | None (both)
    settings: APISettings = Depends(settings_dep),
) -> Page[JobHistoryItem]:
    """Completed/failed jobs, most recently finished first — the Jobs page's
    "Processed" tab."""
    page = max(page, 1)
    size = min(page_size or settings.default_page_size, settings.max_page_size)
    items, total = svc.list_job_history(db, page=page, page_size=size, status=status)
    return Page[JobHistoryItem](
        items=[JobHistoryItem(**item) for item in items], page=page, page_size=size, total=total
    )


@router.get("/{job_id}", response_model=JobStatus)
def get_job(job_id: uuid.UUID, db: Session = Depends(db_session)) -> JobStatus:
    job = svc.get_job(db, job_id)
    if not job:
        raise VideoError(f"No job {job_id}", code="not_found")
    return _job_status(job)
