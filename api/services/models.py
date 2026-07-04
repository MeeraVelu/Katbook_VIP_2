"""
api/services/models.py — SQLAlchemy 2.0 ORM models mirroring the Alembic schema.

The schema is *owned* by Alembic (``database/versions``); these classes are the
read/write mapping the API and worker use. The generated ``fts`` column and the
``embedding`` vector are declared read-only here (populated by SQL / the pipeline)
so ORM flushes never try to write them.
"""

from __future__ import annotations

import datetime as dt
import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Double,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from api.settings import get_api_settings


class Base(DeclarativeBase):
    pass


class Video(Base):
    __tablename__ = "videos"

    video_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    source_path: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str | None] = mapped_column(Text)
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    duration_sec: Mapped[float | None] = mapped_column(Double)
    language: Mapped[str | None] = mapped_column(Text)
    has_speech: Mapped[bool | None] = mapped_column(Boolean)
    tagging_path: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, nullable=False, default="queued")
    is_duplicate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    canonical_video_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("videos.video_id")
    )
    error_message: Mapped[str | None] = mapped_column(Text)
    runtime: Mapped[dict] = mapped_column(JSONB, default=dict)
    stage_timings: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    segments: Mapped[list[Segment]] = relationship(
        back_populates="video", cascade="all, delete-orphan", order_by="Segment.seg_index"
    )


class Segment(Base):
    __tablename__ = "segments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    video_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("videos.video_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    seg_index: Mapped[int] = mapped_column(Integer, nullable=False)
    start_sec: Mapped[float] = mapped_column(Double, nullable=False)
    end_sec: Mapped[float] = mapped_column(Double, nullable=False)
    topic: Mapped[str | None] = mapped_column(Text)
    subject: Mapped[str | None] = mapped_column(Text)
    grade_level: Mapped[str | None] = mapped_column(Text)
    difficulty: Mapped[str | None] = mapped_column(Text)
    content_type: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    subtopics: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    summary: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Double)
    transcript_text: Mapped[str | None] = mapped_column(Text)
    ocr: Mapped[str | None] = mapped_column(Text)
    extra: Mapped[dict] = mapped_column(JSONB, default=dict)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(get_api_settings().embed_dim))
    # generated column — read-only from the ORM's perspective
    fts: Mapped[str | None] = mapped_column(
        TSVECTOR, nullable=True, insert_default=None, info={"read_only": True}
    )

    video: Mapped[Video] = relationship(back_populates="segments")


class Job(Base):
    __tablename__ = "jobs"

    job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    video_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("videos.video_id", ondelete="CASCADE")
    )
    state: Mapped[str] = mapped_column(String, nullable=False, default="queued")
    current_stage: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stage_timings: Mapped[dict] = mapped_column(JSONB, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    enqueued_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
