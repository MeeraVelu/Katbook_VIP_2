"""app/routers/search.py — semantic / keyword / hybrid search over segments."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.deps import db_session, require_api_key, settings_dep
from app.schemas.search import SearchHit, SearchMode, SearchResponse
from app.services import search as svc
from app.settings import APISettings

router = APIRouter(
    prefix="/api/v1/search", tags=["search"], dependencies=[Depends(require_api_key)]
)


@router.get("", response_model=SearchResponse)
def search(
    q: str = Query(..., min_length=1, description="Free-text query."),
    mode: SearchMode = SearchMode.semantic,
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(db_session),
    settings: APISettings = Depends(settings_dep),
) -> SearchResponse:
    limit = min(limit, settings.max_page_size)
    actual_mode, hits = svc.search(db, q, mode.value, limit)
    return SearchResponse(
        query=q,
        mode=SearchMode(actual_mode),
        count=len(hits),
        results=[SearchHit(**h) for h in hits],
    )
