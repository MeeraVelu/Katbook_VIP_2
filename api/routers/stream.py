"""
api/routers/stream.py — serve the source video file for in-dashboard playback.

``GET /api/v1/videos/{video_id}/stream`` reads the video's ``source_path`` from the
DB and streams the file from disk (the API container mounts the same ``/data/inbox``
volume the worker writes to). Range requests are honoured — Starlette's
``FileResponse`` emits ``Accept-Ranges`` + ``206 Partial Content`` — so the HTML5
player can seek to a segment's start time.

Auth note: this route is DELIBERATELY not under the videos router's blanket
``X-API-Key`` header check. A browser ``<video>`` element cannot send custom
headers, so the key is accepted from either the ``X-API-Key`` header OR a ``key``
query param (the UI's ``streamUrl`` appends it). Auth is skipped entirely when
``API_KEY`` is unset, exactly like :func:`api.deps.require_api_key`.
"""

from __future__ import annotations

import mimetypes
import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from api.deps import db_session, settings_dep
from api.services.models import Video
from api.services.videos import VideoError
from api.settings import APISettings

router = APIRouter(prefix="/api/v1/videos", tags=["stream"])


@router.get("/{video_id}/stream")
def stream_video(
    video_id: uuid.UUID,
    request: Request,
    key: str | None = Query(default=None, description="API key (media elements can't send headers)"),
    db: Session = Depends(db_session),
    settings: APISettings = Depends(settings_dep),
) -> FileResponse:
    # Auth: header OR query param (a <video> src can only carry a query param).
    if settings.api_key:
        provided = request.headers.get("X-API-Key") or key
        if provided != settings.api_key:
            raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")

    video = db.get(Video, video_id)
    if video is None:
        raise VideoError(f"No video {video_id}", code="not_found")

    path = video.source_path
    if not path or not os.path.isfile(path):
        # File was deleted after processing (or never on this box). The UI shows a
        # "Video file not available" placeholder and keeps rendering the segments.
        raise HTTPException(status_code=404, detail="Video file not available")

    media_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
    # No `filename=` -> inline playback (not a download); FileResponse adds
    # Accept-Ranges and serves 206 for Range requests so the player can seek.
    return FileResponse(path, media_type=media_type)
