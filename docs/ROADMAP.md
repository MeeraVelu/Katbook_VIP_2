# POC → Production Roadmap

The POC is a faithful **vertical slice** of the full architecture. Each component below already
works at POC grade; the right column is what makes it production-grade. Nothing needs a rewrite —
it's hardening and swapping infrastructure.

## Maturity by component

| Component | POC (now) | Production target |
|---|---|---|
| **Compute** | Kaggle T4×2 (free, ephemeral) | Cloud GPU (A10/L4/A100) on RunPod / Modal / GKE (containerize the pipeline first) |
| **Trigger** | manual upload + Run All | REST API `POST /videos` → enqueue job |
| **Orchestration** | sequential loop | RabbitMQ/SQS queue + autoscaling workers |
| **Packaging** | notebook + script | container image in a registry, CI/CD |
| **ASR** | Whisper medium/large-v3 | Whisper large-v3 + word-level + speaker attribution |
| **LLM tagging** | Qwen2.5-7B 4-bit | **Qwen3-32B via vLLM** (multi-GPU, guided JSON / function-calling) |
| **Vision** | CLIP-base, YOLOv8n, EasyOCR | CLIP-large, domain-tuned detector, multilingual OCR (`ta`,`hi`) |
| **Embeddings** | MiniLM 384-d | larger multilingual embedder; re-rank stage |
| **Durable store** | Neon free Postgres | managed Postgres (HA) + object storage (S3) for video/frames |
| **Vector search** | pgvector + Qdrant local | Qdrant **server** cluster (or pgvector at scale) |
| **Keyword search** | Postgres tsvector | Elasticsearch/OpenSearch |
| **Search front-end** | Gradio demo / `search.py` | authenticated API + web app, rate limiting |
| **Reliability** | per-video try/except | retries, dead-letter queue, idempotency keys |
| **Observability** | print logs + `stage_timings` | structured logs, Prometheus/Grafana, tracing, alerts |
| **Quality loop** | none | human-review UI → corrections feed back as fine-tuning/eval data |

## Target production topology

```
  client ──POST /videos──> API (FastAPI) ──enqueue──> RabbitMQ
                                                          │
                                            ┌─────────────┴─────────────┐
                                         worker 1   worker 2   worker N   (GPU, the container image)
                                            │  process_video() per job   │
                                            └─────────────┬─────────────┘
                          ┌───────────────────────────────┼───────────────────────────────┐
                     S3 (frames/video)            Postgres (metadata+pgvector)       Qdrant cluster
                                                          │
                                              API /search ──> semantic + keyword + filters ──> web app
```

## Suggested next 3 steps (in order)

1. **Containerize & run off-Kaggle.** Wrap the pipeline in a Docker image (CUDA base + the deps from
   the notebook's Cell 1) and run one video on a rented GPU (RunPod/Modal). Proves the pipeline is
   portable — removes the Kaggle ceiling. *(Deferred until a GPU host is available.)*
2. **Add an API + queue.** Small FastAPI service: `POST /videos` stores the file to S3 and enqueues a
   job; a worker (the container) pulls jobs and runs `process_video()`. Now it's a service, not a script.
3. **Upgrade the LLM + observability.** Swap Qwen-7B → Qwen3-32B on vLLM behind a `fuse()` call; add
   structured logging + Prometheus metrics on `stage_timings`. This lifts both quality and operability.

Each step is independent and shippable — you can stop at any maturity level that fits the need.
