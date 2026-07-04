# Katbook Video Intelligence Platform (VIP)

Turns lecture / animation videos into **per-segment structured tags** — topic,
subject, grade level, difficulty, tags, summary, plus a 1024-d vector embedding —
stored in Postgres so you can search a whole video library by **meaning** or by
**keyword**. Handles **narrated and silent** videos in **any language**.

This is the **production** system: an API-first, Dockerized service stack for a
dedicated **NVIDIA RTX 5090 (32 GB, Blackwell)** server. The original free-Kaggle
POC lives in [`legacy/`](legacy/README.md).

```
frontend ──HTTP──> api (FastAPI, no ML) ──> redis queue ──> worker (Celery, GPU)
                        │                                        │
                        ├── postgres 16 + pgvector <────────────┤ (upsert + job status)
                        └── search (semantic/keyword/hybrid)     └── vllm (Qwen2.5-7B FP8 tagging)

pipeline per video: voice/silent router → transcribe (any lang) → adaptive frames
   → CLIP scenes + gated YOLO/OCR + BLIP-2 captions → segment → LLM tags → Postgres
```

## What's here

Root holds only tooling entry-points; everything else is grouped by domain (each
folder has its own one-line `README.md`).

```
api/         API domain — FastAPI service (routers/schemas/services), no ML, no UI
pipeline/    pipeline domain — router, ingest, audio, visual, nlp, segment, tagging, storage
worker/      jobs domain — Celery worker (one video per task, per-stage progress)
ui/          UI domain — static operator console (vanilla HTML/JS, no build) via nginx
database/    database domain — Alembic schema migrations (owns the schema)
docker/      container domain — Dockerfile.api/.worker/.ui + entrypoint/healthcheck
scripts/     ops CLIs — cli, verify_gpu, smoke, reembed, backup, export_tensorrt, make_test_video
tests/       pytest suite (CPU, models mocked)
docs/        DEPLOYMENT · API · DATABASE · ARCHITECTURE · PLAN · CLEANUP
legacy/      retired Kaggle POC (notebook, kaggle_run, sync/search scripts)

# root (tooling entry-points only)
docker-compose.yml  docker-compose.override.dev.yml   # production stack (8 services) + CPU/dev override
requirements.txt  requirements-worker.txt             # API image deps / worker (GPU) image deps
pyproject.toml                                         # build + ruff/mypy/pytest config, dev extras ([dev])
alembic.ini  Makefile  .env.example  .gitignore  .dockerignore  README.md
```

## Deploy (the short version)

Full runbook: **[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)**. On the GPU box:

```bash
# 0) prove the GPU stack works FIRST (catches "old CUDA on Blackwell")
pip install torch --index-url https://download.pytorch.org/whl/cu128
python scripts/verify_gpu.py            # expect RESULT: PASS

# 1) configure secrets
cp .env.example .env                    # set POSTGRES_PASSWORD, API_KEY, CORS_ORIGINS

# 2) build + start (migrate runs Alembic before api/worker)
docker compose up -d
curl -s localhost:8000/ready            # ready:true when DB+Redis+worker GPU are good
```

**The single command your GPU box runs to bring the whole system up:**

```bash
docker compose up -d --build
```

## Use it

```bash
# register a video (dedup pre-check runs before enqueue)
curl -X POST localhost:8000/api/v1/videos -H "X-API-Key: $API_KEY" \
  -H 'Content-Type: application/json' -d '{"source_path":"/data/inbox/lesson.mp4"}'

# enqueue the whole backlog
curl -X POST localhost:8000/api/v1/videos/batch -H "X-API-Key: $API_KEY" \
  -H 'Content-Type: application/json' -d '{"folder":"/data/inbox"}'

# search
curl "localhost:8000/api/v1/search?q=time+period+of+a+pendulum&mode=hybrid" -H "X-API-Key: $API_KEY"
```

Or with the operator CLI: `python scripts/cli.py enqueue-folder /data/inbox`,
`... watch <job_id>`, `... search "..." --mode hybrid`. Full API for the frontend
team: **[docs/API.md](docs/API.md)**.

### Console UI

A bundled, no-build operator console ships in [`ui/`](ui/README.md) (served by the
`ui` compose service at **http://localhost:8080**): browse/filter videos, view a
record + segments, register/upload/batch, watch live job progress, and search
(semantic/keyword/hybrid). It's a **separate static container** — the API process
still loads no UI; the browser calls the API over HTTP, so keep this origin in
`CORS_ORIGINS`. Set the API URL + `X-API-Key` in the console's top bar.

## Verify without a GPU

Everything is verifiable on CPU:

```bash
pip install -e ".[dev]"
make lint          # ruff
make test          # pytest — all green on CPU, models mocked
make smoke         # full pipeline on a generated 10s clip (tiny models, stub tagger, no DB)
docker compose config    # compose is valid
```

## Preserved safety rules

- **Only byte-identical (SHA-256) files are deduplicated** — recorded as a
  reference to their canonical, never reprocessed. Same-topic/different-content
  videos are **never** auto-merged.
- **Deletes are soft** (status flag) — content and segments are retained.
- **Idempotent**: `video_id = uuid5(source_path)`; re-runs UPSERT.

## Profiles

`KVIP_PROFILE` = `production` (RTX 5090: large-v3 / ViT-L-14 / YOLO11x / BGE-M3 /
Qwen-FP8-vLLM) · `fast`/`balanced`/`quality` (T4-class) · `smoke` (tiny CPU models
+ stub tagger, for the smoke test/CI). See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
