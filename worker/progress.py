"""
worker/progress.py — bridge the pipeline's per-stage ``progress`` callback to the
job row, so ``GET /api/v1/jobs/{id}`` shows the live stage + accumulated timings.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

from api.services import jobs as jobs_svc
from api.services.db import session_scope


def make_progress(job_id: uuid.UUID) -> Callable[[str, dict], None]:
    """Return ``callback(stage, info)`` that persists the current stage + timings.

    Each call is its own short transaction (there are only ~8 stages per video),
    keeping job status fresh without holding a connection across the whole run.
    """

    def _cb(stage: str, info: dict) -> None:
        try:
            with session_scope() as s:
                jobs_svc.mark_stage(s, job_id, stage, info.get("stage_timings"))
        except Exception:
            # progress reporting must never crash the pipeline
            pass

    return _cb
