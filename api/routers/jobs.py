"""api/routers/jobs.py — job status (live stage + timings)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.deps import db_session, require_api_key
from api.schemas.jobs import JobStatus
from api.services import jobs as svc
from api.services.videos import VideoError

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"], dependencies=[Depends(require_api_key)])


@router.get("/{job_id}", response_model=JobStatus)
def get_job(job_id: uuid.UUID, db: Session = Depends(db_session)) -> JobStatus:
    job = svc.get_job(db, job_id)
    if not job:
        raise VideoError(f"No job {job_id}", code="not_found")
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
