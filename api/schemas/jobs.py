"""Response models for the jobs endpoint."""

from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel


class JobStatus(BaseModel):
    job_id: uuid.UUID
    video_id: uuid.UUID | None = None
    state: str  # queued | processing | done | failed
    current_stage: str | None = None
    attempts: int = 0
    stage_timings: dict = {}
    error: str | None = None
    enqueued_at: dt.datetime | None = None
    started_at: dt.datetime | None = None
    finished_at: dt.datetime | None = None
    elapsed_sec: float | None = None


class ActiveJob(JobStatus):
    """A JobStatus plus the filename, so the Jobs page's "Processing" tab
    doesn't need a second lookup to know what's currently running."""

    video_filename: str | None = None


class JobHistoryItem(BaseModel):
    """One row of the Jobs page's "Processed" tab — completed/failed jobs."""

    job_id: uuid.UUID
    video_id: uuid.UUID
    video_filename: str | None = None
    status: str  # done | failed
    subject: str | None = None
    segment_count: int = 0
    processing_duration_sec: float | None = None
    completed_at: dt.datetime | None = None
    error: str | None = None
