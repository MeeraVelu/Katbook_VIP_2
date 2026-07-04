"""Request/response models for the videos endpoints."""

from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, Field


class DedupVerdict(BaseModel):
    is_duplicate: bool
    canonical_video_id: uuid.UUID | None = None
    content_hash: str | None = None
    reason: str


class RegisterVideoRequest(BaseModel):
    """Register a video already present on the server filesystem for processing."""

    source_path: str = Field(..., description="Absolute path on the server (e.g. under the inbox).")
    force: bool = Field(
        False, description="Reprocess even if already present (ignored for exact duplicates)."
    )


class RegisterVideoResponse(BaseModel):
    job_id: uuid.UUID | None = Field(
        None, description="Null when the input was an exact duplicate (not enqueued)."
    )
    video_id: uuid.UUID
    status: str = Field(..., description="queued | duplicate | exists")
    dedup: DedupVerdict
    message: str


class BatchRequest(BaseModel):
    """Enqueue every video matched by a glob or a folder (the 95k backlog)."""

    glob: str | None = Field(None, description="Glob pattern, e.g. /data/inbox/**/*.mp4")
    folder: str | None = Field(
        None, description="Folder to scan recursively for known video extensions."
    )
    force: bool = False


class BatchItem(BaseModel):
    source_path: str
    video_id: uuid.UUID
    job_id: uuid.UUID | None
    status: str
    is_duplicate: bool


class BatchResponse(BaseModel):
    enqueued: int
    duplicates: int
    skipped_existing: int
    total: int
    items: list[BatchItem]


class SegmentOut(BaseModel):
    seg_index: int
    start_sec: float
    end_sec: float
    topic: str | None = None
    subject: str | None = None
    grade_level: str | None = None
    difficulty: str | None = None
    content_type: str | None = None
    tags: list[str] = []
    subtopics: list[str] = []
    summary: str | None = None
    confidence: float | None = None
    transcript_text: str | None = None
    ocr: str | None = None
    scenes: list[str] = []
    objects: list[str] = []
    captions: list[str] = []


class VideoSummary(BaseModel):
    video_id: uuid.UUID
    source_path: str
    status: str
    language: str | None = None
    has_speech: bool | None = None
    tagging_path: str | None = None
    duration_sec: float | None = None
    file_size_bytes: int | None = None
    is_duplicate: bool = False
    canonical_video_id: uuid.UUID | None = None
    segment_count: int = 0
    created_at: dt.datetime | None = None
    updated_at: dt.datetime | None = None


class VideoRollup(BaseModel):
    subject: str | None = None
    grade: str | None = None
    difficulty: str | None = None
    primary_topic: str | None = None
    topics: list[str] = []
    all_tags: list[str] = []


class VideoDetail(VideoSummary):
    content_hash: str | None = None
    error_message: str | None = None
    stage_timings: dict = {}
    runtime: dict = {}
    rollup: VideoRollup = VideoRollup()
    segments: list[SegmentOut] = []


class SoftDeleteResponse(BaseModel):
    video_id: uuid.UUID
    status: str
    message: str
