"""
worker/tasks.py — the Celery tasks that run the pipeline.

``process_video`` runs ONE video end-to-end via ``pipeline.process_one_video``:
  * shared small models (embedder + spaCy) are loaded ONCE per worker process and
    reused across tasks (the heavy per-stage models are managed inside the
    pipeline, one in VRAM at a time);
  * **transient** failures (DB / download / network) retry with exponential
    backoff; **poison** inputs (corrupt/undecodable video, bad config) are marked
    failed and skipped — never retried in a loop that would waste the GPU;
  * per-stage progress is written to the job row (see worker/progress.py);
  * ``acks_late`` + the pipeline's transcript checkpoint give graceful shutdown:
    a killed task is re-queued and resumes cheaply.
"""

from __future__ import annotations

import uuid

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy import text

from api.services import jobs as jobs_svc
from api.services.db import get_engine, session_scope
from pipeline.config import load_config
from pipeline.logging_config import bind, configure_logging, get_logger
from pipeline.pipeline import process_one_video
from worker.progress import make_progress

_log = get_logger("worker.tasks")
_shared: dict = {}

# Exception type names treated as transient (retry). Everything else = poison.
_TRANSIENT_MARKERS = (
    "OperationalError",
    "DisconnectionError",
    "InterfaceError",
    "ConnectionError",
    "ConnectionResetError",
    "TimeoutError",
    "gaierror",
    "RedisError",
    "BrokenPipeError",
    "ReadTimeout",
    "APIConnectionError",
)


def _device() -> str:
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def _shared_models(cfg: dict, device: str):
    """Load embedder + spaCy once per worker process."""
    if "embedder" not in _shared:
        import spacy
        from sentence_transformers import SentenceTransformer

        _log.info(f"loading shared embedder ({cfg['EMBED_MODEL']}) + spaCy (once per worker)")
        _shared["embedder"] = SentenceTransformer(cfg["EMBED_MODEL"], device=device)
        try:
            _shared["nlp"] = spacy.load("en_core_web_sm")
        except Exception:
            import subprocess
            import sys

            subprocess.run(
                [sys.executable, "-m", "spacy", "download", "en_core_web_sm"], check=False
            )
            _shared["nlp"] = spacy.load("en_core_web_sm")
    return _shared["embedder"], _shared["nlp"]


def _is_transient(exc: Exception) -> bool:
    chain = []
    cur: BaseException | None = exc
    while cur is not None:
        chain.append(type(cur).__name__)
        cur = cur.__cause__ or cur.__context__
    return any(m in name for name in chain for m in _TRANSIENT_MARKERS)


def _fail_video(video_id: str, message: str) -> None:
    try:
        with get_engine().begin() as cx:
            cx.execute(
                text(
                    "UPDATE videos SET status='failed', error_message=:m, updated_at=now() "
                    "WHERE video_id=:v"
                ),
                {"m": message[:2000], "v": video_id},
            )
    except Exception:
        _log.warning("could not mark video failed", extra={"video_id": video_id})


def _load_worker_config() -> dict:
    """Config with the GPU-tier layer applied + the vector(1024) invariant asserted."""
    cfg = load_config(apply_tier=True)
    dim = int(cfg.get("EMBED_DIM") or 0)
    if dim != 1024:
        raise RuntimeError(
            f"EMBED_DIM={dim} but the database column is vector(1024). The embedder "
            f"must be BGE-M3 (1024-d) on every GPU tier — check KVIP_EMBED_MODEL/"
            f"KVIP_EMBED_DIM. (model={cfg.get('EMBED_MODEL')!r})"
        )
    return cfg


@shared_task(bind=True, name="worker.tasks.process_video", max_retries=5)
def process_video(self, job_id: str, video_id: str, source_path: str) -> dict:
    configure_logging()
    bind(job_id=job_id[:8], video_id=video_id[:8])
    from pipeline.gpu_profile import log_startup

    log_startup()
    cfg = _load_worker_config()
    device = _device()

    with session_scope() as s:
        jobs_svc.mark_started(s, uuid.UUID(job_id), profile=cfg.get("PROFILE"))

    try:
        embedder, nlp = _shared_models(cfg, device)
        engine = get_engine()
        summary = process_one_video(
            source_path,
            cfg,
            embedder=embedder,
            nlp=nlp,
            engine=engine,
            device=device,
            progress=make_progress(uuid.UUID(job_id)),
        )
        with session_scope() as s:
            jobs_svc.mark_done(s, uuid.UUID(job_id), summary.get("stage_timings"))
        _log.info("job done", extra={"summary": summary})
        return summary

    except SoftTimeLimitExceeded:
        # treat as transient: the video may just be long; retry once more
        _log.warning("soft time limit hit; retrying", extra={"job_id": job_id})
        raise self.retry(countdown=30, exc=SoftTimeLimitExceeded()) from None

    except Exception as exc:  # noqa: BLE001 — classify then route
        transient = _is_transient(exc)
        _log.error(
            f"job error ({'transient' if transient else 'poison'}): {exc}",
            extra={"job_id": job_id},
            exc_info=True,
        )
        if transient and self.request.retries < self.max_retries:
            countdown = min(600, 10 * (2**self.request.retries))
            raise self.retry(countdown=countdown, exc=exc) from exc
        # poison input (or retries exhausted): mark failed, move on — no GPU wasted
        with session_scope() as s:
            jobs_svc.mark_failed(s, uuid.UUID(job_id), str(exc))
        _fail_video(video_id, str(exc))
        return {"video_id": video_id[:8], "status": "failed", "error": str(exc)[:200]}


@shared_task(name="worker.tasks.process_batch")
def process_batch(
    glob_pat: str | None = None, folder: str | None = None, force: bool = False
) -> dict:
    """Discover a folder/glob and enqueue one ``process_video`` per file, reusing
    the API's registration/dedup logic. Lets the CLI kick off the 95k backlog
    without going through HTTP."""
    from api.services import videos as vsvc

    with session_scope() as s:
        result = vsvc.register_batch(s, glob_pat, folder, force=force)
    _log.info("batch enqueued", extra={"enqueued": result["enqueued"], "total": result["total"]})
    return {k: result[k] for k in ("enqueued", "duplicates", "skipped_existing", "total")}
