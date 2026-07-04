# Legacy — Kaggle POC artifacts

These are the **original proof-of-concept** files that ran the pipeline on a free
Kaggle T4 GPU with a Neon/Supabase free-tier Postgres. They are kept for history
and are **not part of the production deployment** (which is Dockerized and
GPU-server-based — see the root `README.md` and `docs/DEPLOYMENT.md`).

| File | What it was |
|---|---|
| `katbook_vip_kaggle.ipynb` | Thin Kaggle notebook runner (install → clone package → set CONFIG → run). |
| `kernel-metadata.json` | Kaggle kernel metadata for `kaggle_run.py`. |
| `kaggle_run.py` | Headless push/run of the notebook via the Kaggle CLI. |
| `sync_results.py` | Laptop tool: mirror Neon Postgres results into `./results`. **Superseded by** `scripts/cli.py export` + the live API. |
| `search.py` | Laptop keyword/semantic search CLI. **Superseded by** `GET /api/v1/search` + `scripts/cli.py search`. |
| `requirements-local.txt` | Laptop-only deps for the two scripts above. **Superseded by** `pyproject.toml [dev]` (typer + httpx) for `scripts/cli.py`. |
| `OPERATIONS.md` | The Kaggle run/sync/troubleshoot runbook. **Superseded by** `docs/DEPLOYMENT.md`. |

The pipeline *logic* these drove was preserved and productionized in
`katbook_vip/`; only the Kaggle/Neon-specific plumbing was retired here.

> Note: `sync_results.py` / `search.py` target the **old** DB schema
> (`segments.llm` JSONB, MiniLM 384-d vectors). They will not run against the new
> production schema unmodified — use the API / `scripts/cli.py` instead.
