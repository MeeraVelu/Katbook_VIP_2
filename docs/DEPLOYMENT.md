# Deployment runbook (RTX 5090 production box)

This is the exact procedure to deploy Katbook VIP on a dedicated NVIDIA **RTX 5090
(32 GB, Blackwell, sm_120)** server. It assumes you have never seen this project.

The app runs in Docker Compose: `api`, `worker` (GPU), `vllm` (GPU), `embeddings`
(CPU), plus the console `ui`. The stateful `postgres`, `redis`, and the one-shot
`migrate` are **optional** (compose profile `infra`): run them in Docker for a
self-contained stack, or point the app at an **external** database (native or
cloud) — see **[§2 Database options](#2-database-options)**.

---

## 0. Host prerequisites

| Requirement | Why | Check |
|---|---|---|
| NVIDIA driver **570+** | Blackwell sm_120 support | `nvidia-smi` (shows driver ≥ 570 and the RTX 5090) |
| **CUDA 12.8+** runtime (via the driver) | cu128 wheels / vLLM | `nvidia-smi` top-right CUDA version ≥ 12.8 |
| Docker Engine + Compose v2 | orchestration | `docker version`, `docker compose version` |
| **NVIDIA Container Toolkit** | GPU inside containers | `docker run --rm --gpus all nvidia/cuda:12.8.1-base-ubuntu24.04 nvidia-smi` |
| Disk: 100+ GB free | model cache + pgdata | `df -h` |

Install the NVIDIA Container Toolkit (Ubuntu):

```bash
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker && sudo systemctl restart docker
```

## 1. Verify the GPU stack FIRST

Before building images, confirm the box can actually run torch on the 5090. This
catches the single most common failure (an older CUDA/torch stack on Blackwell):

```bash
python3 -m venv .verify && . .verify/bin/activate
pip install torch --index-url https://download.pytorch.org/whl/cu128
python scripts/verify_gpu.py
```

You want `RESULT: PASS`. If the GPU matmul fails with *"no kernel image is
available for execution on the device"*, your torch was not built for sm_120 — use
the cu128 (or cu128 **nightly**) index, see Troubleshooting #1.

## 2. Database options

**Postgres** (with **pgvector**) is the choice here — you decide **where it runs**;
the app code is identical either way, it just reads `DATABASE_URL` from `.env`. The
bundled `postgres` and the one-shot `migrate` service live in the **`infra` compose
profile**, so a plain `docker compose up -d` skips them and the app connects to an
external database. **Redis is NOT in the profile — it always runs as a local
Compose service** (the Celery broker is local, and managed DB providers don't offer
Redis); point `REDIS_URL` elsewhere only if you run a dedicated Redis.

| Option | Postgres runs… | Start command | `.env` template |
|---|---|---|---|
| **A — Self-contained** (default) | in Docker (bundled) | `docker compose --profile infra up -d` | `.env.example` |
| **B — Native Postgres** (recommended prod) | natively on the host | `docker compose up -d` | `.env.production` |
| **C — Cloud managed** (Supabase/Aiven/Neon) | at a cloud provider | `docker compose up -d` | `.env.production` (cloud URL) |

In every option Redis is the bundled Compose service (`redis://redis:6379/0`).

### Option A — Self-contained (evaluation / testing)

Simplest: Compose runs Postgres, Redis, migrations, and the app together.

```bash
cp .env.example .env
# edit: POSTGRES_PASSWORD, API_KEY, CORS_ORIGINS; DATABASE_URL points at the
# bundled `postgres` service by name (postgres:5432) — leave as-is.
docker compose --profile infra up -d     # `migrate` runs Alembic first, then api/worker
```

Data lives in the `pgdata` Docker volume. Good for a quick trial; the DB's
lifecycle is tied to Docker.

### Option B — Native Postgres (recommended for production)

Run Postgres 16 + pgvector natively so the data persists **independently of Docker**
(survives `docker compose down -v`, easier to back up, tune, and monitor). Redis
stays the bundled Compose service, so you only install Postgres.

```bash
# 1) install on the server (Ubuntu)
sudo apt install postgresql-16 postgresql-16-pgvector

# 2) create the database + user, enable pgvector
sudo -u postgres createuser katbook -P            # prompts for a password
sudo -u postgres createdb katbook_vip -O katbook
psql -U katbook -d katbook_vip -c "CREATE EXTENSION vector;"

# 3) migrate the schema ONCE by hand (no `migrate` container in this path)
#    run from the repo root, in a venv with the API deps installed:
DATABASE_URL=postgresql://katbook:<pass>@localhost:5432/katbook_vip alembic upgrade head

# 4) point the app at it and start WITHOUT the bundled DB
cp .env.production .env
# edit DATABASE_URL (replace CHANGE_ME with the real password), API_KEY, CORS_ORIGINS.
# NOTE: inside a container "localhost" is the CONTAINER, not the host — to reach a
# host-native Postgres use the host LAN IP, or host.docker.internal via
# `extra_hosts: ["host.docker.internal:host-gateway"]` on Linux.
docker compose up -d                              # postgres + migrate skipped; redis runs
```

Re-run `alembic upgrade head` by hand whenever you deploy a version that adds a
migration (the `migrate` container only runs under `--profile infra`).

### Option C — Cloud managed (Aiven / Supabase / Neon)

Identical to Option B, but the database lives at a managed provider — no local
Postgres to install (Redis is still the bundled Compose service). Create the
instance, enable the `vector` extension (most providers expose `CREATE EXTENSION
vector;`), then put the provider's connection string in `.env.production`:

```bash
cp .env.production .env
# DATABASE_URL=postgresql://<user>:<pass>@<host>:5432/<db>?sslmode=require
alembic upgrade head            # migrate the cloud DB once, from your workstation
docker compose up -d            # redis runs; postgres + migrate skipped
```

**Supabase specifics** (verified): use the **Session pooler** connection string
(Dashboard → Connect → *Session pooler*), NOT the *Direct* one:

- Direct host `db.<ref>.supabase.co` is **IPv6-only** → fails from Docker (no A
  record). The Session pooler `aws-<n>-<region>.pooler.supabase.com` is IPv4.
- Use port **5432** (session mode). Avoid port **6543** (transaction pooler) — it
  breaks psycopg3 prepared statements and Alembic.
- The user is `postgres.<project-ref>`, the database is `postgres`, and append
  `?sslmode=require`:

  ```
  DATABASE_URL=postgresql://postgres.<ref>:<pass>@aws-<n>-<region>.pooler.supabase.com:5432/postgres?sslmode=require
  ```

Enable pgvector from the Supabase SQL editor (`create extension if not exists
vector;`) before `alembic upgrade head`.

> ⚠️ **Latency:** a cloud DB adds network round-trips to **every** DB write. The
> worker upserts a video + all its segments per job; on the 95k backlog that
> latency compounds. Prefer a DB in the **same region/VPC** as the GPU box, or use
> Option B (native, loopback-fast) for the bulk ingest and reserve cloud for
> smaller/managed deployments.

### Connect a DB GUI (pgAdmin / DBeaver) — all options

Same client, the host/port just differ by option:

| Option | Host | Port | Notes |
|---|---|---|---|
| A (bundled) | `localhost` (or `127.0.0.1`) | `5432` | Only reachable if the port is published — the dev override (`docker-compose.override.dev.yml`) maps `127.0.0.1:5432:5432`. The production compose does **not** publish it; add a `ports:` mapping or tunnel `docker compose exec postgres psql`. |
| B (native) | `localhost` / server IP | `5432` | Direct — it's a normal Postgres on the host. |
| C (cloud) | provider host | `5432` | Enable **SSL/TLS** (`sslmode=require`); use the provider's credentials. |

In **DBeaver**: New Connection → PostgreSQL → Host/Port/Database (`katbook_vip`) /
User (`katbook`) / Password → Test Connection. In **pgAdmin**: Register → Server →
*Connection* tab, same fields. The `segments.embedding` column shows as `vector`;
install pgvector-aware tooling if you want to inspect vectors, otherwise it renders
as text. Secrets live only in `.env` (gitignored). The frontend talks to the API
with the `X-API-Key` header = `API_KEY`, from an origin listed in `CORS_ORIGINS`.

## 3. Build & start

```bash
docker compose build            # builds api (slim) + worker (cu128) images
# Option A (bundled DB):   docker compose --profile infra up -d   # migrate runs first
# Option B/C (external DB): docker compose up -d                  # DB skipped; migrate by hand
docker compose ps               # all healthy? (vllm takes a few minutes to load Qwen)
docker compose logs -f worker   # watch the worker come up + publish its GPU heartbeat
```

Readiness:

```bash
curl -s localhost:8000/health          # {"status":"ok",...}
curl -s localhost:8000/ready           # ready:true once DB + Redis + worker GPU heartbeat are good
```

The build also produces the **console UI** (React SPA via nginx) at
**http://localhost:${UI_PORT:-8080}** — open it, click the key icon, and enter your
`API_KEY`. It proxies to the API same-origin, so no CORS setup is needed for it.

### Verify the detected GPU tier

The worker auto-detects its tier (`cpu | t4_16gb | rtx_high | rtx5090 |
datacenter`) and adapts the model knobs. Confirm it:

```bash
docker compose logs worker | grep 'GPU tier'          # e.g. "GPU tier = rtx5090 (source=auto)"
curl -s localhost:8000/ready | jq '.details.gpu'      # {tier, device, vram_gb, capability}
```

The console header (**GpuTierChip**) and **System** page show the same tier.

**Override the tier** (e.g. force a smaller profile, or pin a tier the heuristics
misread) by setting `GPU_PROFILE` in `.env` and restarting the worker:

```bash
# GPU_PROFILE=rtx5090   # cpu | t4_16gb | rtx_high | rtx5090 | datacenter
docker compose up -d worker
```

> Invariant: embeddings are **BGE-M3 (1024-d) on every tier** (the DB is
> `vector(1024)`); the worker fails fast at startup if `EMBED_DIM != 1024`.

## 4. First video (smoke on the real box)

```bash
# put a file where the worker can read it (the shared inbox volume)
docker compose cp ./sample.mp4 worker:/data/inbox/sample.mp4

# register it (dedup pre-check runs before enqueue)
curl -s -X POST localhost:8000/api/v1/videos \
  -H "X-API-Key: $API_KEY" -H 'Content-Type: application/json' \
  -d '{"source_path":"/data/inbox/sample.mp4"}'
# -> {"job_id":"...","status":"queued",...}

# watch it process (live stage + timings)
curl -s localhost:8000/api/v1/jobs/<job_id> -H "X-API-Key: $API_KEY"
# or: python scripts/cli.py watch <job_id>

# search once it's done
curl -s "localhost:8000/api/v1/search?q=your+topic&mode=hybrid" -H "X-API-Key: $API_KEY"
```

## 5. Kick off the 95k backlog

Put the corpus on a disk mounted into the worker's inbox volume, then:

```bash
curl -s -X POST localhost:8000/api/v1/videos/batch \
  -H "X-API-Key: $API_KEY" -H 'Content-Type: application/json' \
  -d '{"folder":"/data/inbox"}'
# or: python scripts/cli.py enqueue-folder /data/inbox
```

Each file becomes a job on the `gpu` queue. The worker processes one at a time;
already-done videos are skipped and exact duplicates are recorded without
reprocessing (the pipeline's Stage-0 hash gate).

## 6. Monitor the queue

```bash
docker compose logs -f worker                       # structured JSON logs
docker compose exec redis redis-cli LLEN gpu        # queue depth
docker compose exec redis redis-cli GET katbook:worker:heartbeat   # worker liveness
curl -s "localhost:8000/api/v1/videos?status=failed" -H "X-API-Key: $API_KEY"  # failures
```

## 7. Add a second GPU worker later

Scaling is horizontal — start another worker container pinned to the second card,
on the same `gpu` queue:

```yaml
# docker-compose.override.yml
services:
  worker2:
    extends:
      file: docker-compose.yml
      service: worker
    environment:
      CUDA_VISIBLE_DEVICES: "1"
```

```bash
docker compose -f docker-compose.yml -f docker-compose.override.yml up -d worker2
```

No code changes; Celery load-balances jobs across both workers.

## 8. Optional: TensorRT for YOLO

On the target GPU (not at image build time):

```bash
docker compose exec worker python scripts/export_tensorrt.py --model yolo11x.pt --half
# then set KVIP_YOLO_MODEL=/path/to/yolo11x.engine in .env and restart the worker
```

## 9. Backups

See `docs/DATABASE.md`. Schedule `scripts/backup.sh` (cron) and copy dumps off-box.

---

## Troubleshooting (top 10)

| # | Symptom | Cause / fix |
|---|---|---|
| 1 | Worker/vLLM crash: **"no kernel image is available for execution on the device"** | The classic **older CUDA stack on Blackwell**. torch/vLLM were not built for sm_120. Install cu128 wheels: `pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128`. If the stable wheel still lacks sm_120, use the **nightly** cu128/cu129 index, and build vLLM from source (`TORCH_CUDA_ARCH_LIST=12.0`, FlashAttention **v2**). `scripts/verify_gpu.py` must PASS. |
| 2 | `torch.cuda.is_available()` is **False** inside the container | NVIDIA Container Toolkit not installed/configured, or `--gpus`/`deploy.reservations` missing. Test: `docker run --rm --gpus all nvidia/cuda:12.8.1-base-ubuntu24.04 nvidia-smi`. Driver must be **570+**. |
| 3 | `vllm` container stuck "starting" / OOM | Qwen + the worker share the 5090. Lower `--gpu-memory-utilization` (compose `vllm.command`, default 0.45) and/or `--max-model-len`. Confirm FP8 is supported by your vLLM version; check `docker compose logs vllm`. |
| 4 | vLLM image "not ready for Blackwell" | Official `vllm/vllm-openai:latest` occasionally lags new GPUs. Pin a known-good tag, or build vLLM from source (see #1). Verify the FP8 flag syntax against current vLLM docs — `--quantization fp8` is the dynamic path. |
| 5 | `migrate` fails: `type "vector" does not exist` | Postgres image must be `pgvector/pgvector:pg16` (it is in compose). The migration runs `CREATE EXTENSION vector`; ensure the DB user can create extensions. |
| 6 | API `/ready` returns 503 | One of DB / Redis / worker-GPU-heartbeat is down. `curl /ready` shows which `checks` failed. For CPU/dev set `READY_REQUIRES_GPU=0`. |
| 7 | Semantic search returns keyword results | The `embeddings` service (query embedding) is down or `EMBEDDINGS_URL` is unset → graceful keyword fallback. Check `docker compose logs embeddings`; ensure the model id matches the worker's embedder (BGE-M3). |
| 8 | Tamil/Hindi OCR error in logs | Expected, non-fatal: EasyOCR falls back to English automatically if `ta`/`hi` weights fail to load. The spoken transcript (Whisper, multilingual) is unaffected. |
| 9 | A video is stuck / job never finishes | Check `docker compose logs worker`. Corrupt inputs are marked `failed` (no retry). Transient DB/network errors retry with backoff. `acks_late` re-queues a video if the worker was killed; the transcript checkpoint makes resume cheap. |
| 10 | Models re-download every restart | The `model-cache` volume (`HF_HOME=/models`) isn't mounted/persisted. Confirm the `model-cache` named volume exists and is mounted in `worker` and `vllm`. |

### Health of the whole stack at a glance

```bash
docker compose ps
curl -s localhost:8000/ready | jq
docker compose exec redis redis-cli GET katbook:worker:info    # GPU name/capability
```
