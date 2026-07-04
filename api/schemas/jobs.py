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
