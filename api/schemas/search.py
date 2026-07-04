"""Response models for the search endpoint."""

from __future__ import annotations

import uuid
from enum import StrEnum

from pydantic import BaseModel


class SearchMode(StrEnum):
    semantic = "semantic"
    keyword = "keyword"
    hybrid = "hybrid"


class SearchHit(BaseModel):
    video_id: uuid.UUID
    seg_index: int
    start_sec: float
    end_sec: float
    topic: str | None = None
    subject: str | None = None
    grade_level: str | None = None
    summary: str | None = None
    score: float


class SearchResponse(BaseModel):
    query: str
    mode: SearchMode
    count: int
    results: list[SearchHit]
