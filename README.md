# Katbook VIP — Kaggle POC (T4×2 → cloud Postgres)

A single notebook that runs the **full 6-stage** Video Intelligence pipeline on Kaggle's free
**GPU T4 × 2**, and writes structured tags + embeddings to a **free cloud Postgres** (pgvector).
Your laptop only edits text — all models run on Kaggle.

**Files**
- `katbook_vip_poc.ipynb` — the notebook to upload to Kaggle (this is the one you run).
- `katbook_vip_poc.py` — same content as editable source (regenerate the .ipynb if you edit it).

---

## Do these ONCE before running (≈15 min)

### 1. Get a free cloud Postgres (Neon — recommended, no card)
1. Go to **https://neon.tech** → sign up (free tier).
2. Create a project → it gives you a **connection string** like
   `postgresql://user:pass@ep-xxx.aws.neon.tech/neondb?sslmode=require`.
3. Copy it. (Supabase works too — use its "Connection string / URI". Both support `pgvector`,
   which the notebook enables automatically with `CREATE EXTENSION vector`.)

### 2. Get a HuggingFace token (for diarization)
1. **https://huggingface.co** → sign up → Settings → **Access Tokens** → create a `read` token.
2. Accept the model terms (one click each, free):
   - https://huggingface.co/pyannote/speaker-diarization-3.1
   - https://huggingface.co/pyannote/segmentation-3.0
   > If you skip this, set `ENABLE_DIARIZATION = False` in Cell 0 — everything else still runs.

### 3. Create the Kaggle notebook
1. https://kaggle.com → **Create → New Notebook**.
2. **File → Import Notebook → Upload** `katbook_vip_poc.ipynb`.

### 4. Turn on GPU + Internet
In the right-hand panel (**⋮ / Settings**):
- **Accelerator → GPU T4 × 2**
- **Internet → On**  (required for pip + model downloads)

### 5. Add your two secrets
**Add-ons → Secrets** (or the right panel → Secrets), add:
| Label | Value |
|---|---|
| `DATABASE_URL` | your Neon/Supabase connection string from step 1 |
| `HF_TOKEN` | your HuggingFace token from step 2 |

Attach both to the notebook (toggle them on).

### 6. Upload your sample video
1. Right panel → **Add Input → Datasets → New Dataset → Upload** your clip (a **2–5 min** lecture
   is ideal for the first run; keeps you well inside the 30 GPU-hrs/week quota).
2. After it attaches, find its path under `/kaggle/input/<your-dataset-name>/<file>.mp4`.
3. Open **Cell 0** and set:
   ```python
   "VIDEO_PATH": "/kaggle/input/your-dataset-name/your-file.mp4",
   ```
   You can also edit `SCENE_LABELS` and `DOMAIN_CONTEXT` (Cell 11) to match Katbook's subjects —
   the doc calls domain-context injection the single biggest accuracy lever.

---

## Run it
**Run All** (or run cells top to bottom). Order of stages:

| Cell | Stage | What it does |
|---|---|---|
| 0 | Config | edit input path + toggles |
| 1 | Install | pip libs (~3–5 min first run) |
| 2–3 | Setup | GPU check, load secrets |
| 4 | Stage 1 | ffmpeg → 16 kHz WAV + frames |
| 5–6 | Stage 2A | Whisper transcribe, langdetect, pyannote diarize, librosa features |
| 7–8 | Stage 2B | CLIP scenes, YOLOv8 objects, EasyOCR text, BLIP-2 captions |
| 9 | Stage 3 | spaCy NER, KeyBERT, embeddings, BERTopic |
| 10 | Stage 5 | temporal segmentation (cosine drop + kneed) |
| 11 | Stage 4 | Qwen 4-bit LLM fusion → structured tags per segment |
| 12 | Stage 6 | write to Postgres (pgvector) + full-text + local Qdrant |
| 13 | Verify | read back, semantic search, full-text search |

Each heavy model is loaded, used, then **freed** (`free_vram`) so a single 16 GB T4 never overflows.

---

## Where your data lives afterward
- **Cloud Postgres** (persists forever): tables `videos` and `segments`. Query from anywhere:
  ```sql
  SELECT seg_index, start_sec, end_sec, llm->>'topic' AS topic, llm->'tags' AS tags
  FROM segments ORDER BY video_id, seg_index;
  ```
  - Semantic search: `ORDER BY embedding <=> '[...]'` (pgvector).
  - Full-text search: `WHERE fts @@ plainto_tsquery('english','your words')`.
- **`/kaggle/working/payload.json`** — full pipeline output, downloadable from the notebook output.
- **`/kaggle/working/qdrant_db/`** — local Qdrant vector store (ephemeral; pgvector is the durable copy).

---

## If something breaks
| Symptom | Fix |
|---|---|
| `CUDA out of memory` | Cell 0: set `ENABLE_BLIP2=False`, lower `MAX_FRAMES` to 30, or `WHISPER_MODEL="medium"`. |
| Diarization error / 403 | Accept the two pyannote model terms (step 2) or set `ENABLE_DIARIZATION=False`. |
| `Video not found` | Fix `VIDEO_PATH` in Cell 0 to the exact `/kaggle/input/...` path. |
| Postgres SSL error | Make sure the URL ends with `?sslmode=require` (Neon needs it). |
| Session timeout | Use a short clip first; Kaggle GPU sessions cap at ~9–12h and 30 GPU-hrs/week. |
| BERTopic skipped | Normal for short videos (<8 windows ≈ <4 min of speech). |

---

## Production gap (vs. the architecture doc)
This POC is a faithful **vertical slice**. To move toward production: swap Qwen2.5-7B → **Qwen3-32B on vLLM**
(multi-GPU), add **RabbitMQ** orchestration, run **Elasticsearch** + **Qdrant server** + on-prem **PostgreSQL**,
use `en_core_web_trf` and full multilingual OCR (`ta`,`hi`), and add the Prometheus/Grafana observability +
human-review feedback loop from the ops mind-map.
