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
ui/          UI domain — React SPA "mission control" console (Vite + Tailwind) via nginx
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
```

Then pick where the **database** runs — the app is identical either way, it just
reads `DATABASE_URL`. Postgres and `migrate` are bundled behind the **`infra`**
compose profile, so a plain `up` skips them for an external DB. **Redis always runs
as a local Compose service** (managed DBs don't provide one).

```bash
# ── Path A · self-contained (bundled Postgres in Docker) — eval/testing ────────
cp .env.example .env                     # set POSTGRES_PASSWORD, API_KEY, CORS_ORIGINS
docker compose --profile infra up -d     # migrate runs Alembic before api/worker

# ── Path B · external DB (cloud e.g. Supabase, or native Postgres) — production ─
#   cloud: enable pgvector + use the connection string (Supabase → SESSION POOLER, :5432)
#   native: sudo apt install postgresql-16 postgresql-16-pgvector
#           sudo -u postgres createdb katbook_vip -O katbook  (createuser katbook -P first)
#   then migrate once:  alembic upgrade head
cp .env.production .env                   # set the real DATABASE_URL, API_KEY, CORS
docker compose up -d                      # postgres + migrate skipped; redis runs

curl -s localhost:8000/ready             # ready:true when DB+Redis+worker GPU are good
```

**The single command to (re)build and bring the system up** — add `--build`:

```bash
docker compose --profile infra up -d --build   # self-contained
docker compose up -d --build                    # external DB (Path B)
```

See **[docs/DEPLOYMENT.md §2 Database options](docs/DEPLOYMENT.md)** for the native
and cloud (Aiven/Supabase/Neon) walkthroughs and DB-GUI (pgAdmin/DBeaver) setup.

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

A **React SPA** "mission control" console ships in [`ui/`](ui/README.md) (built by
`docker/Dockerfile.ui`, served by nginx as the `ui` compose service at
**http://localhost:8080**): library + segment timelines, live job PipelineStepper,
`/`-key command-bar search (semantic/keyword/hybrid), ingest, and a System page
with the live GPU tier. It's a **separate container** — the API process loads no UI;
nginx proxies `/api`,`/health`,`/ready` to the API **same-origin** (no CORS needed
for the console). Set your `X-API-Key` via the header key icon. Any external
frontend can replace it over the same API.

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
