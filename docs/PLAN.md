# PLAN — POC → Production transformation

Status legend: **[new]** create · **[mod]** modify · **[move]** relocate to `legacy/` · **[keep]** unchanged

This plan turns the validated `katbook_vip/` POC monolith into an API-first,
Dockerized, GPU-server-ready system **without changing pipeline logic**. Every
item is verifiable on CPU (mocked unit tests + a real tiny-model smoke run); the
GPU-specific parts are correct-by-construction and documented.

---

## 0. Non-negotiable behaviors preserved

- **Dedup safety rule**: only *byte-identical* (SHA-256) re-uploads are deduped
  → recorded as a reference to their canonical, never reprocessed. Same-topic /
  different-content videos are **never** auto-deleted or auto-merged. Deletes are
  **soft** (status flag) only.
- **Idempotency**: `video_id = uuid5(URL, source_path)`; re-runs UPSERT.
- **Voice/Silent router** decisions, prompts, and the strict per-segment JSON
  contract are unchanged. The consistency pass is unchanged.
- **Per-video export JSON shape** (`export.build_result`) is byte-shape identical;
  DB reconstruction (`scripts/cli.py export`) rebuilds the same JSON.
- **One-model-at-a-time** VRAM discipline (`utils.managed_model`) is kept; on 32 GB
  the production profile may keep the *visual* stack resident (`RESIDENT_VISUAL_STACK`).

---

## 1. Config & core refactor (`katbook_vip/`)

- **[new] `katbook_vip/settings.py`** — `pydantic-settings` `Settings` (+ `Profile`
  models) layered over the **existing env names** (`KVIP_*`, `DATABASE_URL`,
  `HF_TOKEN`). Adds a `production` profile; keeps `fast`/`balanced`/`quality` and
  a new `smoke` profile (tiny CPU models). Validates `EMBED_MODEL`/`EMBED_DIM`
  fail-fast on mismatch. Exposes `.as_config()` → the same flat dict the pipeline
  already consumes, so pipeline modules keep using `cfg["KEY"]`.
- **[mod] `katbook_vip/config.py`** — thin compat shim: `load_config()` now builds
  the dict from `Settings`; `SCENE_LABELS`/`REALWORLD_SCENES`/`TEXTY_SCENES` stay
  here. New production defaults documented in the profile table.
- **[new] `katbook_vip/logging_config.py`** — stdlib logging + JSON formatter;
  `contextvars` for `request_id` / `video_id` / `stage`. `configure_logging()`.
- **[mod] `katbook_vip/utils.py`** — `log()` routes through structured logger
  (keeps the same call sites); `managed_model`, timers, checkpoint unchanged.
  Add `set_log_context()` helper.
- **[mod] `katbook_vip/tagging.py`** — extract the LLM call behind a backend
  (`llm_backend.generate_json`). **Same prompts, same schema, same recovery.**
  Add one retry-on-malformed. `embed_segments` uses `EMBED_DIM` not hardcoded 384.
- **[new] `katbook_vip/llm_backend.py`** — `TAGGING_BACKEND` = `vllm` (OpenAI
  client, `base_url`/`model` from env), `inprocess` (current 4-bit/FP16 path,
  bitsandbytes optional), or `stub` (deterministic, for CPU CI). Model/URL swap =
  config only (7B→14B).
- **[mod] `katbook_vip/ingest.py`** — `extract_audio`/frame extract gain optional
  `-hwaccel cuda` (NVDEC) with automatic CPU fallback (`FFMPEG_HWACCEL` env).
  SHA-256 + `file_size` helpers kept. Adds `partial_hash` unused-safe helper only
  if needed (dedup stays SHA-256-based, behavior preserved).
- **[mod] `katbook_vip/visual.py`** — `RESIDENT_VISUAL_STACK` flag (keep CLIP+YOLO
  +OCR resident during the visual stage on 32 GB); YOLO11x via profile; OCR
  `en,ta,hi` with the existing en-fallback. Gating logic unchanged.
- **[mod] `katbook_vip/nlp_stage.py`** — window embedding dim from settings.
- **[mod] `katbook_vip/storage.py`** — **remove inline DDL** (`_ensure_schema`);
  assume Alembic-migrated schema. Rewrite upsert to the new structured `segments`
  columns + `extra`/`ocr`. Keep dedup helpers (`find_canonical_by_hash`,
  `store_duplicate`) and idempotent UPSERT semantics. psycopg (v3) driver.
- **[mod] `katbook_vip/pipeline.py`** — add an optional `progress` callback invoked
  after each stage (worker uses it to update job state). Behavior otherwise identical.
- **[mod] `katbook_vip/run.py`** — structured logging; settings-based; batch CLI kept.
- **[mod] `katbook_vip/__init__.py`** — version → `3.0.0`. (Packaging is
  `pyproject.toml`-only; the legacy `setup.py` shim was removed in the cleanup pass.)

## 2. API service (`app/`) — FastAPI, **zero ML deps, zero UI**

- **[new] `app/main.py`** — app factory, CORS (env origins), request-ID +
  JSON-logging middleware, exception handlers (consistent error envelope),
  routers, `/health`, `/ready`, OpenAPI at `/docs`.
- **[new] `app/settings.py`** — API settings (API key, CORS, DB pool, Redis URL,
  page size, vLLM URL passthrough).
- **[new] `app/deps.py`** — DB session dep, `X-API-Key` auth dep, request-id dep.
- **[new] `app/errors.py`** — error envelope model + handlers (422/401/404/409/500).
- **[new] `app/schemas/{common,videos,jobs,search}.py`** — Pydantic v2 req/resp
  models for every endpoint.
- **[new] `app/routers/videos.py`** — `POST /api/v1/videos` (path or multipart to
  inbox; SHA-256 dedup pre-check **before** enqueue; returns `job_id` + verdict),
  `POST /api/v1/videos/batch` (folder/glob), `GET /api/v1/videos` (paginated +
  filters), `GET /api/v1/videos/{id}` (record + segments), `DELETE` (soft-delete).
- **[new] `app/routers/jobs.py`** — `GET /api/v1/jobs/{id}` (queued/processing+stage
  +timings/done/failed).
- **[new] `app/routers/search.py`** — `GET /api/v1/search?q&mode&limit` — semantic
  (pgvector cosine), keyword (tsvector), hybrid (RRF). Ports `search.py` logic.
- **[new] `app/routers/health.py`** — `/health` liveness, `/ready` (DB + Redis +
  worker GPU heartbeat).
- **[new] `app/services/db.py`** — SQLAlchemy 2.0 engine (pool_size/max_overflow/
  pool_pre_ping/statement_timeout from env), session factory.
- **[new] `app/services/models.py`** — ORM: `Video`, `Segment`, `Job`.
- **[new] `app/services/videos.py`** — register/list/get/soft-delete + dedup pre-check.
- **[new] `app/services/jobs.py`** — job read/update helpers (shared with worker).
- **[new] `app/services/search.py`** — semantic/keyword/hybrid(RRF); query embedder
  loaded lazily (CPU) **only in the search service**, never in request path models.
- **[new] `app/services/queue.py`** — Celery `send_task` enqueue wrapper.
- **[new] `app/__init__.py`, `app/schemas/__init__.py`, `app/routers/__init__.py`,
  `app/services/__init__.py`**.

## 3. Worker service (`worker/`) — Celery

- **[new] `worker/celery_app.py`** — Celery(broker=Redis, backend=Redis), 1 task/
  GPU concurrency, task routes, acks_late, `worker_prefetch_multiplier=1`.
- **[new] `worker/tasks.py`** — `process_video(job_id, video_path)` imports
  `katbook_vip.process_one_video`; retries w/ exp backoff for transient (DB/IO);
  **no retry** for poison input (corrupt video) → mark failed + move on; batch
  enqueue task; graceful shutdown (finish current, checkpoint, exit).
- **[new] `worker/progress.py`** — stage→DB/Redis job updates (drives `GET /jobs`).
- **[new] `worker/heartbeat.py`** — periodic GPU-visible heartbeat key in Redis
  read by `/ready`.
- **[new] `worker/__init__.py`**.

## 4. Database (Alembic + productionized schema)

- **[new] `alembic.ini`, `alembic/env.py`, `alembic/script.py.mako`**.
- **[new] `alembic/versions/0001_initial_schema.py`** — creates `vector` ext;
  `videos`, `segments`, `jobs`; indexes: **HNSW** on `segments.embedding`
  (`vector_cosine_ops`, m=16, ef_construction=64), GIN on `fts`, btree on
  `videos.content_hash`, `videos.status`, `segments.video_id`. `segments.fts` =
  generated column (`transcript_text || summary || topic`). `vector(1024)`.
  - `segments` extra columns beyond the spec core (documented, lossless): `ocr text`,
    `extra jsonb` (scenes/objects/captions + speaker_role/language/has_visual_content/
    subject_raw/flags). Enables identical JSON reconstruction + silent-path evidence.
- **[new] `scripts/reembed.py`** — re-embed legacy 384-d rows to 1024-d (documented).

## 5. Scripts (`scripts/`)

- **[new] `verify_gpu.py`** — driver/CUDA/torch versions, capability≥(12,0) handling,
  tiny matmul, load+free a small model, PASS/FAIL + remediation. **Run first.**
- **[new] `cli.py`** (typer) — enqueue folder, watch progress, search, reprocess one,
  `export` (rebuild results JSON from DB — replaces `sync_results.py`).
- **[new] `backup.sh`** — `pg_dump` to dated file (+ restore steps in DATABASE.md).
- **[new] `export_tensorrt.py`** — optional YOLO11x → TensorRT export (off by default).
- **[new] `make_test_video.py`** — ffmpeg-generate a 10 s clip (voice + silent).
- **[new] `smoke.py`** — run the full pipeline on the generated clip, CPU, tiny
  models, `stub` tagger, JSON-only. Proves wiring end-to-end, no GPU.

## 6. Docker

- **[new] `docker/Dockerfile.api`** — slim `python:3.12-slim`, multi-stage, non-root,
  no ML deps.
- **[new] `docker/Dockerfile.worker`** — CUDA 12.8 base (`nvidia/cuda:12.8.*-runtime-
  ubuntu24.04`), torch from cu128 index, all pipeline deps, `HF_HOME` volume,
  non-root, healthcheck. Version pins + "verify at build" note.
- **[new] `docker/entrypoint-worker.sh`, `docker/healthcheck.py`**.
- **[new] `docker-compose.yml`** — `api`, `worker` (GPU reservation), `vllm`
  (`vllm/vllm-openai`, `--model Qwen/Qwen2.5-7B-Instruct --quantization fp8`),
  `redis` (vol), `postgres` (`pgvector/pgvector:pg16`, vol, healthcheck), one-shot
  `migrate` (`depends_on: service_completed_successfully`). Named vols: pgdata,
  redisdata, model-cache, video-inbox, results. Restart `unless-stopped`, log rotation.
- **[new] `docker-compose.override.dev.yml`** — CPU/dev overrides (no GPU, stub tagger).
- **[new] `.dockerignore`**.

## 7. Tests (`tests/`) — all pass on CPU, models mocked

- `conftest.py` (fixtures, monkeypatch model loaders), `test_router.py`,
  `test_dedup.py`, `test_segment_math.py`, `test_tagger_json.py` (recovery robustness),
  `test_settings_profiles.py`, `test_storage_idempotency.py` (dockerized PG via
  compose test profile / skipped if unavailable), `test_api_videos.py`,
  `test_api_jobs.py`, `test_api_search.py` (httpx + fake queue).

## 8. Packaging / tooling

- **[new] `pyproject.toml`** — project metadata, ruff + ruff-format + mypy(`app/`) config.
- **[new] `Makefile`** — `smoke`, `test`, `lint`, `format`, `typecheck`, `migrate`,
  `up`, `down`, `verify-gpu`.
- **[new] pinned requirements** — consolidated in the cleanup pass to two root
  files: `requirements.txt` (API image) + `requirements-worker.txt` (worker, cu128);
  dev/test/CLI deps live in `pyproject.toml [project.optional-dependencies].dev`.
- **[new] `.env.example`** — every variable, commented. Secrets via env only.
- **[mod] `.gitignore`** — add `.env`, inbox, model-cache, `*.sqlite`.

## 9. Docs & legacy

- **[new] `docs/DEPLOYMENT.md`** — full runbook + top-10 troubleshooting (incl.
  "old CUDA stack on Blackwell" + vLLM from-source fallback).
- **[new] `docs/API.md`** — every endpoint w/ curl; CORS + API-key contract.
- **[new] `docs/DATABASE.md`** — mermaid schema, why PG+pgvector, HNSW vs IVFFlat,
  index/ef_search tuning, 95k capacity math, backup/restore, first-time setup.
- **[mod] `docs/ARCHITECTURE.md`** — new service diagram (mermaid), POC→prod diffs,
  preserved safety rules.
- **[mod] `README.md`** — rewritten for production.
- **[move] `legacy/`** — `katbook_vip_kaggle.ipynb`, `kernel-metadata.json`,
  `kaggle_run.py`, `sync_results.py`, `search.py`, old `README`/`OPERATIONS` Kaggle
  bits, `requirements-local.txt`. Nothing deleted.

---

## Execution order
1. Core refactor (settings, logging, llm_backend, tagging, storage, ingest, visual, nlp, pipeline).
2. Alembic schema + models.
3. Worker (Celery) → API (FastAPI).
4. Scripts + Docker + requirements + pyproject + Makefile + .env.example.
5. Tests.
6. Docs + legacy move.
7. `ruff`, `pytest`, `make smoke`, `docker compose config` → final checklist.
