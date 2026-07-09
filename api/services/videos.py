"""
api/services/videos.py — business logic for the videos endpoints.

Responsibilities:
  * Deterministic ``video_id = uuid5(URL, source_path)`` (matches the pipeline).
  * **Exact-duplicate (SHA-256) pre-check BEFORE enqueue** — a byte-identical
    re-upload is recorded as a reference to its canonical and never processed.
  * Idempotent registration: an already-``done`` video is not re-enqueued unless
    ``force``.
  * List / detail with structured filters; **soft-delete only** (status flag),
    honouring the never-auto-delete safety rule.
"""

from __future__ import annotations

import glob as globlib
import os
import uuid

from sqlalchemy import Select, func, select, text
from sqlalchemy.orm import Session

from api.services import jobs as jobs_svc
from api.services.models import Segment, Video
from api.services.queue import enqueue_video
from pipeline.ingest import file_sha256, file_size_bytes

NAMESPACE = uuid.NAMESPACE_URL
VIDEO_EXTS = ("mp4", "webm", "mov", "mkv", "avi", "m4v")


class VideoError(Exception):
    """Raised for client-correctable problems (missing file, etc.)."""

    def __init__(self, message: str, code: str = "bad_request"):
        super().__init__(message)
        self.code = code


def video_id_for(source_path: str) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, source_path)


def _find_canonical(session: Session, content_hash: str, exclude_id: uuid.UUID) -> uuid.UUID | None:
    if not content_hash:
        return None
    row = session.execute(
        text(
            "SELECT video_id FROM videos WHERE content_hash=:h "
            "AND COALESCE(is_duplicate, FALSE)=FALSE AND status <> 'soft_deleted' "
            "AND video_id<>:vid ORDER BY created_at LIMIT 1"
        ),
        {"h": content_hash, "vid": str(exclude_id)},
    ).first()
    return row[0] if row else None


def register_video(session: Session, source_path: str, force: bool = False) -> dict:
    """Register/enqueue one server-side video. Returns a dict the router maps to
    ``RegisterVideoResponse``."""
    if not os.path.isfile(source_path):
        raise VideoError(f"No file at {source_path!r}", code="not_found")

    vid = video_id_for(source_path)
    content_hash = file_sha256(source_path)
    size = file_size_bytes(source_path)

    existing = session.get(Video, vid)
    if existing and existing.status == "done" and not existing.is_duplicate and not force:
        return {
            "job_id": None,
            "video_id": vid,
            "status": "exists",
            "dedup": {
                "is_duplicate": False,
                "canonical_video_id": None,
                "content_hash": content_hash,
                "reason": "already processed (use force=true to reprocess)",
            },
            "message": "Video already processed.",
        }

    filename = os.path.basename(source_path)

    canonical = _find_canonical(session, content_hash, vid)
    if canonical:
        # record the exact duplicate as a reference — never reprocessed
        session.execute(
            text("""
            INSERT INTO videos(video_id, source_path, video_filename, content_hash,
                file_size_bytes, status, is_duplicate, canonical_video_id, updated_at)
            VALUES (:vid,:sp,:vf,:h,:fs,'done',TRUE,:can, now())
            ON CONFLICT (video_id) DO UPDATE SET
                is_duplicate=TRUE, canonical_video_id=:can, content_hash=:h,
                status='done', updated_at=now()"""),
            {
                "vid": str(vid),
                "sp": source_path,
                "vf": filename,
                "h": content_hash,
                "fs": size,
                "can": str(canonical),
            },
        )
        return {
            "job_id": None,
            "video_id": vid,
            "status": "duplicate",
            "dedup": {
                "is_duplicate": True,
                "canonical_video_id": canonical,
                "content_hash": content_hash,
                "reason": "byte-identical to an existing video",
            },
            "message": f"Exact duplicate of {str(canonical)[:8]}; not reprocessed.",
        }

    # fresh (or forced) work: upsert the video as queued, create a job, enqueue
    session.execute(
        text("""
        INSERT INTO videos(video_id, source_path, video_filename, content_hash,
            file_size_bytes, status, is_duplicate, updated_at)
        VALUES (:vid,:sp,:vf,:h,:fs,'queued',FALSE, now())
        ON CONFLICT (video_id) DO UPDATE SET
            source_path=:sp, video_filename=:vf, content_hash=:h, file_size_bytes=:fs,
            status='queued', is_duplicate=FALSE, canonical_video_id=NULL,
            error_message=NULL, updated_at=now()"""),
        {"vid": str(vid), "sp": source_path, "vf": filename, "h": content_hash, "fs": size},
    )
    job = jobs_svc.create_job(session, vid, video_filename=filename)
    session.flush()
    enqueue_video(job.job_id, vid, source_path)
    return {
        "job_id": job.job_id,
        "video_id": vid,
        "status": "queued",
        "dedup": {
            "is_duplicate": False,
            "canonical_video_id": None,
            "content_hash": content_hash,
            "reason": "new content",
        },
        "message": "Queued for processing.",
    }


def _discover(glob_pat: str | None, folder: str | None) -> list[str]:
    if glob_pat:
        return sorted(p for p in globlib.glob(glob_pat, recursive=True) if os.path.isfile(p))
    if folder:
        found: list[str] = []
        for root, _dirs, files in os.walk(folder):
            for f in files:
                if f.rsplit(".", 1)[-1].lower() in VIDEO_EXTS:
                    found.append(os.path.join(root, f))
        return sorted(found)
    return []


def register_batch(
    session: Session, glob_pat: str | None, folder: str | None, force: bool = False
) -> dict:
    """Enqueue a whole folder/glob (the 95k backlog). Per-file exact-duplicate
    detection is handled by the worker's Stage-0 hash gate, so this stays fast on
    very large batches; already-``done`` videos are skipped unless ``force``."""
    paths = _discover(glob_pat, folder)
    items, enq, dups, skipped = [], 0, 0, 0
    for p in paths:
        vid = video_id_for(p)
        existing = session.get(Video, vid)
        if existing and existing.status == "done" and not force:
            skipped += 1
            items.append(
                {
                    "source_path": p,
                    "video_id": vid,
                    "job_id": None,
                    "status": "exists",
                    "is_duplicate": existing.is_duplicate,
                }
            )
            continue
        filename = os.path.basename(p)
        session.execute(
            text("""
            INSERT INTO videos(video_id, source_path, video_filename, status, is_duplicate, updated_at)
            VALUES (:vid,:sp,:vf,'queued',FALSE, now())
            ON CONFLICT (video_id) DO UPDATE SET
                source_path=:sp, video_filename=:vf, status='queued', error_message=NULL, updated_at=now()"""),
            {"vid": str(vid), "sp": p, "vf": filename},
        )
        job = jobs_svc.create_job(session, vid, video_filename=filename)
        session.flush()
        enqueue_video(job.job_id, vid, p)
        enq += 1
        items.append(
            {
                "source_path": p,
                "video_id": vid,
                "job_id": job.job_id,
                "status": "queued",
                "is_duplicate": False,
            }
        )
    return {
        "enqueued": enq,
        "duplicates": dups,
        "skipped_existing": skipped,
        "total": len(paths),
        "items": items,
    }


def _list_query(
    subject: str | None,
    grade_level: str | None,
    language: str | None,
    has_speech: bool | None,
    status: str | None,
    include_deleted: bool,
) -> Select:
    q = select(Video)
    if not include_deleted:
        q = q.where(Video.status != "soft_deleted")
    if status:  # status is a fixed enum from the dropdown — exact match
        q = q.where(Video.status == status)
    if language:  # forgiving: case-insensitive substring ("ta" matches "Tamil")
        q = q.where(Video.language.ilike(f"%{language}%"))
    if has_speech is not None:
        q = q.where(Video.has_speech == has_speech)
    if subject or grade_level:
        # subject/grade live on segments — restrict to videos having a matching one.
        # Filters are case-insensitive partial matches so "phys" finds "Physics".
        sub = select(Segment.video_id)
        if subject:
            sub = sub.where(Segment.subject.ilike(f"%{subject}%"))
        if grade_level:
            sub = sub.where(Segment.grade_level.ilike(f"%{grade_level}%"))
        q = q.where(Video.video_id.in_(sub))
    return q


def list_videos(
    session: Session,
    *,
    page: int,
    page_size: int,
    subject: str | None = None,
    grade_level: str | None = None,
    language: str | None = None,
    has_speech: bool | None = None,
    status: str | None = None,
    include_deleted: bool = False,
) -> tuple[list[Video], int]:
    q = _list_query(subject, grade_level, language, has_speech, status, include_deleted)
    total = session.execute(select(func.count()).select_from(q.subquery())).scalar_one()
    rows = (
        session.execute(
            q.order_by(Video.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        )
        .scalars()
        .all()
    )
    return list(rows), int(total)


def segment_count(session: Session, video_id: uuid.UUID) -> int:
    return int(
        session.execute(
            select(func.count()).select_from(Segment).where(Segment.video_id == video_id)
        ).scalar_one()
    )


def get_video(session: Session, video_id: uuid.UUID) -> Video | None:
    return session.get(Video, video_id)


def list_segments(session: Session, video_id: uuid.UUID) -> list[Segment]:
    return list(
        session.execute(
            select(Segment).where(Segment.video_id == video_id).order_by(Segment.seg_index)
        )
        .scalars()
        .all()
    )


def list_facets(session: Session) -> dict:
    """Distinct subject/grade/language values already present in the (non-deleted)
    library — powers the Library page's filter autocomplete."""
    subjects = (
        session.execute(
            select(Segment.subject)
            .distinct()
            .join(Video, Video.video_id == Segment.video_id)
            .where(Segment.subject.isnot(None), Video.status != "soft_deleted")
            .order_by(Segment.subject)
        )
        .scalars()
        .all()
    )
    grades = (
        session.execute(
            select(Segment.grade_level)
            .distinct()
            .join(Video, Video.video_id == Segment.video_id)
            .where(Segment.grade_level.isnot(None), Video.status != "soft_deleted")
            .order_by(Segment.grade_level)
        )
        .scalars()
        .all()
    )
    languages = (
        session.execute(
            select(Video.language)
            .distinct()
            .where(Video.language.isnot(None), Video.status != "soft_deleted")
            .order_by(Video.language)
        )
        .scalars()
        .all()
    )
    return {"subjects": list(subjects), "grades": list(grades), "languages": list(languages)}


def soft_delete(session: Session, video_id: uuid.UUID) -> Video | None:
    """Soft-delete ONLY (status flag). Never removes rows or segments — honours
    the safety rule that only exact byte-duplicates are ever deduplicated and no
    content is auto-deleted."""
    v = session.get(Video, video_id)
    if not v:
        return None
    v.status = "soft_deleted"
    session.flush()
    return v
