"""
api/routers/videos.py — register / list / detail / soft-delete video endpoints.

POST accepts a **server filesystem path** (JSON) or a **multipart upload** to the
watched inbox; both run the SHA-256 dedup pre-check before enqueueing. All GPU
work happens in the worker — this router only touches Postgres + the queue.
"""

from __future__ import annotations

import os
import shutil
import uuid
from collections import Counter

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from api.deps import db_session, require_api_key, settings_dep
from api.schemas.common import Page
from api.schemas.videos import (
    BatchRequest,
    BatchResponse,
    RegisterVideoRequest,
    RegisterVideoResponse,
    SegmentOut,
    SoftDeleteResponse,
    VideoDetail,
    VideoRollup,
    VideoSummary,
)
from api.services import videos as svc
from api.services.models import Segment, Video
from api.settings import APISettings

router = APIRouter(
    prefix="/api/v1/videos", tags=["videos"], dependencies=[Depends(require_api_key)]
)

_DIFF_RANK = {"beginner": 0, "intermediate": 1, "advanced": 2, "expert": 3}


def _segment_out(s: Segment) -> SegmentOut:
    extra = s.extra or {}
    return SegmentOut(
        seg_index=s.seg_index,
        start_sec=s.start_sec,
        end_sec=s.end_sec,
        topic=s.topic,
        subject=s.subject,
        grade_level=s.grade_level,
        difficulty=s.difficulty,
        content_type=s.content_type,
        tags=list(s.tags or []),
        subtopics=list(s.subtopics or []),
        summary=s.summary,
        confidence=s.confidence,
        transcript_text=s.transcript_text,
        ocr=s.ocr,
        scenes=extra.get("scenes", []) or [],
        objects=extra.get("objects", []) or [],
        captions=extra.get("captions", []) or [],
    )


def _summary(v: Video, seg_count: int) -> VideoSummary:
    return VideoSummary(
        video_id=v.video_id,
        source_path=v.source_path,
        status=v.status,
        language=v.language,
        has_speech=v.has_speech,
        tagging_path=v.tagging_path,
        duration_sec=v.duration_sec,
        file_size_bytes=v.file_size_bytes,
        is_duplicate=v.is_duplicate,
        canonical_video_id=v.canonical_video_id,
        segment_count=seg_count,
        created_at=v.created_at,
        updated_at=v.updated_at,
    )


def _rollup(segments: list[SegmentOut]) -> VideoRollup:
    subjects = [s.subject for s in segments if s.subject]
    grades = [s.grade_level for s in segments if s.grade_level]
    diffs = [s.difficulty for s in segments if s.difficulty]
    primary = max(segments, key=lambda s: s.end_sec - s.start_sec).topic if segments else None
    topics, seen = [], set()
    for s in segments:
        if s.topic and s.topic not in seen:
            seen.add(s.topic)
            topics.append(s.topic)
    tags, seen_t = [], set()
    for s in segments:
        for t in s.tags:
            if t and t not in seen_t:
                seen_t.add(t)
                tags.append(t)
    return VideoRollup(
        subject=Counter(subjects).most_common(1)[0][0] if subjects else None,
        grade=Counter(grades).most_common(1)[0][0] if grades else None,
        difficulty=max(diffs, key=lambda d: _DIFF_RANK.get(d, 0)) if diffs else None,
        primary_topic=primary,
        topics=topics,
        all_tags=tags,
    )


@router.post("", response_model=RegisterVideoResponse, status_code=202)
def register_video(
    body: RegisterVideoRequest, db: Session = Depends(db_session)
) -> RegisterVideoResponse:
    result = svc.register_video(db, body.source_path, force=body.force)
    return RegisterVideoResponse(**result)


@router.post("/upload", response_model=RegisterVideoResponse, status_code=202)
def upload_video(
    file: UploadFile = File(...),
    force: bool = Form(False),
    db: Session = Depends(db_session),
    settings: APISettings = Depends(settings_dep),
) -> RegisterVideoResponse:
    os.makedirs(settings.inbox_dir, exist_ok=True)
    dest = os.path.join(
        settings.inbox_dir, os.path.basename(file.filename or f"{uuid.uuid4().hex}.mp4")
    )
    with open(dest, "wb") as out:
        shutil.copyfileobj(file.file, out)
    result = svc.register_video(db, dest, force=force)
    return RegisterVideoResponse(**result)


@router.post("/batch", response_model=BatchResponse, status_code=202)
def register_batch(body: BatchRequest, db: Session = Depends(db_session)) -> BatchResponse:
    return BatchResponse(**svc.register_batch(db, body.glob, body.folder, force=body.force))


@router.get("", response_model=Page[VideoSummary])
def list_videos(
    db: Session = Depends(db_session),
    page: int = 1,
    page_size: int | None = None,
    subject: str | None = None,
    grade_level: str | None = None,
    language: str | None = None,
    has_speech: bool | None = None,
    status: str | None = None,
    include_deleted: bool = False,
    settings: APISettings = Depends(settings_dep),
) -> Page[VideoSummary]:
    page = max(page, 1)
    size = min(page_size or settings.default_page_size, settings.max_page_size)
    rows, total = svc.list_videos(
        db,
        page=page,
        page_size=size,
        subject=subject,
        grade_level=grade_level,
        language=language,
        has_speech=has_speech,
        status=status,
        include_deleted=include_deleted,
    )
    items = [_summary(v, svc.segment_count(db, v.video_id)) for v in rows]
    return Page[VideoSummary](items=items, page=page, page_size=size, total=total)


@router.get("/{video_id}", response_model=VideoDetail)
def get_video(video_id: uuid.UUID, db: Session = Depends(db_session)) -> VideoDetail:
    v = svc.get_video(db, video_id)
    if not v:
        raise svc.VideoError(f"No video {video_id}", code="not_found")
    segs = [_segment_out(s) for s in v.segments]
    base = _summary(v, len(segs)).model_dump()
    return VideoDetail(
        **base,
        content_hash=v.content_hash,
        error_message=v.error_message,
        stage_timings=v.stage_timings or {},
        runtime=v.runtime or {},
        rollup=_rollup(segs),
        segments=segs,
    )


@router.delete("/{video_id}", response_model=SoftDeleteResponse)
def delete_video(video_id: uuid.UUID, db: Session = Depends(db_session)) -> SoftDeleteResponse:
    v = svc.soft_delete(db, video_id)
    if not v:
        raise svc.VideoError(f"No video {video_id}", code="not_found")
    return SoftDeleteResponse(
        video_id=video_id,
        status=v.status,
        message="Soft-deleted (status flag only; content and segments are retained).",
    )
