# Deployment runbook (RTX 5090 production box)

This is the exact procedure to deploy Katbook VIP on a dedicated NVIDIA **RTX 5090
(32 GB, Blackwell, sm_120)** server. It assumes you have never seen this project.

Everything runs in Docker Compose: `api`, `worker` (GPU), `vllm` (GPU),
`embeddings` (CPU), `redis`, `postgres`, and a one-shot `migrate`.

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

## 2. Configure `.env`

```bash
cp .env.example .env
# edit .env: set POSTGRES_PASSWORD, API_KEY, CORS_ORIGINS (the frontend origin),
# and confirm KVIP_PROFILE=production, KVIP_EMBED_MODEL=BAAI/bge-m3, KVIP_EMBED_DIM=1024.
```

Secrets live only in `.env` (gitignored). The frontend talks to the API with the
`X-API-Key` header = `API_KEY`, from an origin listed in `CORS_ORIGINS`.

## 3. Build & start

```bash
docker compose build            # builds api (slim) + worker (cu128) images
docker compose up -d            # starts everything; `migrate` runs Alembic first
docker compose ps               # all healthy? (vllm takes a few minutes to load Qwen)
docker compose logs -f worker   # watch the worker come up + publish its GPU heartbeat
```

Readiness:

```bash
curl -s localhost:8000/health          # {"status":"ok",...}
curl -s localhost:8000/ready           # ready:true once DB + Redis + worker GPU heartbeat are good
```

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
