# CLEANUP — dependency audit (Phase 1)

Audit of all **104 tracked files** (`git ls-files`; `.venv/` is already untracked).
Classifications: **NEEDED** (referenced) · **ENTRY-POINT** (root-required tooling) ·
**LEGACY** (POC-only, lives in `legacy/`) · **ORPHAN** (zero references) ·
**SECRET** · **RUNTIME-JUNK**.

**Bottom line:** the repo is already close to the target layout. Only a handful of
real changes: delete `setup.py`, collapse `requirements/` → 2 root files, move
`PLAN.md`/`CLEANUP.md` into `docs/`, and add one-line READMEs to domain folders.
No source packages move; no imports change.

---

## Actions summary (what Phase 2 will do)

| Action | Files | Why safe |
|---|---|---|
| **DELETE** | `setup.py` | Only self-reference (`setup()`); `pyproject.toml` is the authoritative build (`[build-system]` + `[project]`). `pip install -e .` uses PEP 660 via setuptools. |
| **CONSOLIDATE** | `requirements/{base,api,worker,dev,local}.txt` → **`requirements.txt`** (API image) + **`requirements-worker.txt`** (worker image) | Only referenced by `Dockerfile.api` (api.txt), `Dockerfile.worker` (worker.txt), `Makefile` + `README` (dev.txt). All 4 references updated. Dev/CLI tooling moves to `pyproject [project.optional-dependencies].dev`. |
| **MOVE** | `PLAN.md` → `docs/PLAN.md`; `CLEANUP.md` → `docs/CLEANUP.md` | No code/config references either (grep = 0). Doc-only. |
| **ADD** | one-line `README.md` in `api/ pipeline/ worker/ database/ docker/ scripts/ tests/ docs/` | `ui/` + `legacy/` already have one. Additive, zero risk. |
| **UPDATE refs** | `docker/Dockerfile.api`, `docker/Dockerfile.worker`, `Makefile`, `README.md`, `docs/PLAN.md` | Repoint requirements paths; `make install-dev` → `pip install -e ".[dev]"`. |
| **KEEP (no change)** | everything else (all of `api/ pipeline/ worker/ ui/ database/ docker/ scripts/ tests/ docs/ legacy/` + root entry-points) | Referenced / in correct domain folder. |
| **FLAG, no git action** | `db_url.txt` (SECRET) | Already **untracked + gitignored** (line 2), 118 B on disk = your live DB URL. `git rm` can't touch an untracked file; deleting the local file would destroy your credential. **Recommend: leave it (out of repo already).** Your call. |

Target requirements scheme after consolidation:
- `requirements.txt` = base infra (pydantic, sqlalchemy, psycopg, pgvector, redis, celery, alembic) + API (fastapi, uvicorn, python-multipart, httpx, openai). Used by `Dockerfile.api`.
- `requirements-worker.txt` = base infra + ML stack (transformers, sentence-transformers, faster-whisper, ultralytics, easyocr, spacy, …). Used by `Dockerfile.worker` (torch/torchvision still installed first from the cu128 index).
- Dev/test/CLI deps (pytest, ruff, mypy, typer, httpx) → `pyproject [project.optional-dependencies].dev`.

---

## Full file table

### Root — ENTRY-POINT (rule B: stay at root)
| File | Class | Evidence | Action |
|---|---|---|---|
| `docker-compose.yml` | ENTRY-POINT | compose CLI | keep |
| `docker-compose.override.dev.yml` | ENTRY-POINT | `compose -f … -f …` | keep |
| `pyproject.toml` | ENTRY-POINT | build/ruff/mypy/pytest config | keep |
| `alembic.ini` | ENTRY-POINT | `alembic` reads it (`env.py`) | keep |
| `Makefile` | ENTRY-POINT | dev/ops targets | keep (update `install-dev`) |
| `.gitignore` | ENTRY-POINT | git | keep |
| `.dockerignore` | ENTRY-POINT | docker build | keep |
| `.env.production.template` | ENTRY-POINT | copy to `.env` (`env_file`), docs | keep |
| `README.md` | ENTRY-POINT | root readme | keep (update layout section) |

### Root — TO CHANGE
| File | Class | Evidence | Action |
|---|---|---|---|
| `setup.py` | ORPHAN | only `setup()` self-call; superseded by `pyproject.toml` | **delete (git rm)** |
| `PLAN.md` | NEEDED (doc) | no code refs | **move → `docs/PLAN.md`** |
| `CLEANUP.md` | NEEDED (doc) | this file | **move → `docs/CLEANUP.md`** |

### `requirements/` — CONSOLIDATE
| File | Class | Evidence | Action |
|---|---|---|---|
| `requirements/base.txt` | NEEDED | `-r base.txt` in api/worker/dev | fold into both root files |
| `requirements/api.txt` | NEEDED | `Dockerfile.api` | → `requirements.txt` |
| `requirements/worker.txt` | NEEDED | `Dockerfile.worker` | → `requirements-worker.txt` |
| `requirements/dev.txt` | NEEDED | `Makefile`, `README` | → `pyproject [dev]` |
| `requirements/local.txt` | ORPHAN | referenced by nothing active (only concept in README) | drop (typer/httpx covered by `[dev]`) |

### `api/` — API domain (NEEDED, keep)
`__init__.py, deps.py, errors.py, main.py, middleware.py, settings.py, routers/{__init__,health,jobs,search,videos}.py, schemas/{__init__,common,jobs,search,videos}.py, services/{__init__,db,jobs,models,queue,search,videos}.py`
→ imported across the FastAPI app + `worker/`; `uvicorn api.main:app` in `Dockerfile.api`. **Keep.** Add `api/README.md`.

### `pipeline/` — pipeline domain (NEEDED, keep)
`__init__.py, __main__.py, audio.py, config.py, export.py, ingest.py, llm_backend.py, logging_config.py, nlp_stage.py, pipeline.py, router.py, run.py, segment.py, settings.py, storage.py, tagging.py, utils.py, visual.py`
→ imported by `worker/tasks.py`, `api/services`, `scripts/`, `tests/`; `__main__.py` = `python -m pipeline` batch entry. **Keep.** Add `pipeline/README.md`.

### `worker/` — jobs domain (NEEDED, keep)
`__init__.py, celery_app.py, heartbeat.py, progress.py, tasks.py`
→ `celery -A worker.celery_app` in `entrypoint-worker.sh`; queue task name in `api/settings`. **Keep.** Add `worker/README.md`.

### `ui/` — UI domain (NEEDED, keep)
`index.html, app.js, styles.css, README.md`
→ `Dockerfile.ui` copies `ui/`; compose `ui` service. **Keep** (already has README).

### `database/` — database domain (NEEDED, keep)
`env.py, script.py.mako, versions/0001_initial_schema.py`
→ `alembic.ini` `script_location=alembic`; `env.py` imports `pipeline.storage`; `script.py.mako` is the revision template; migration run by compose `migrate`. **Keep.** Add `database/README.md`.

### `docker/` — docker domain (NEEDED, keep)
`Dockerfile.api, Dockerfile.worker, Dockerfile.ui, entrypoint-worker.sh, healthcheck.py`
→ referenced by compose `build.dockerfile`; `entrypoint-worker.sh` + `healthcheck.py` referenced by `Dockerfile.worker`. **Keep.** Add `docker/README.md`. (Update the two `COPY requirements/…` lines.)

### `scripts/` — ops CLIs (NEEDED, keep)
`cli.py, verify_gpu.py, backup.sh, reembed.py, export_tensorrt.py, make_test_video.py, smoke.py`
→ `make smoke`→`smoke.py`→`make_test_video.py`; `make verify-gpu`; `katbook` console-script→`cli.py` (pyproject). **Keep.** Add `scripts/README.md`.

### `tests/` — NEEDED, keep
`__init__.py, conftest.py, test_{api_jobs,api_search,api_videos,dedup,router,segment_math,settings_profiles,storage_idempotency,tagger_json}.py`
→ `pytest` (pyproject `testpaths=["tests"]`). **Keep.** Add `tests/README.md`.

### `docs/` — NEEDED, keep
`API.md, ARCHITECTURE.md, DATABASE.md, DEPLOYMENT.md`
→ linked from `README.md` + cross-linked. **Keep.** Add `docs/README.md` (index). PLAN.md + CLEANUP.md land here.

### `legacy/` — LEGACY (keep in legacy/)
`README.md, OPERATIONS.md, kaggle_run.py, pipeline_kaggle.ipynb, kernel-metadata.json, requirements-local.txt, search.py, sync_results.py`
→ self-contained Kaggle POC; only referenced within `legacy/`. **Keep as-is** (already isolated).

### Untracked (for reference — not in `git ls-files`)
| Path | Class | Action |
|---|---|---|
| `db_url.txt` | SECRET | already gitignored + untracked → **leave local** (your DB URL) |
| `.venv/`, `results/`, `outputs/`, `uploads/`, `__pycache__/`, `*.pyc`, `.pytest_cache/`, `.ruff_cache/` | RUNTIME-JUNK | already gitignored + untracked → no action |

---

**No source package moves. No import changes. 6 files touched for the requirements
repoint; `setup.py` deleted; 2 docs moved; 8 folder READMEs added.**

Approve and I'll run Phase 2 + Phase 3 (ruff, pytest 53/1, compileall, alembic
history, compose config ×2, node --check) and commit.
