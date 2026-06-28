# Katbook VIP — Video Intelligence Platform (POC)

Turn raw lecture videos into **searchable, structured knowledge**. A 6-stage GPU pipeline
(transcribe → see → understand → segment → tag → store) converts each video into per-segment
**topic / subject / grade / tags / summary + embeddings**, stored in cloud Postgres and queryable
by meaning or keyword.

The pipeline runs **free on Kaggle's GPU**; your laptop only pulls and queries the results.

```
 videos ──▶ [ 6-stage pipeline on Kaggle GPU ] ──▶ Postgres (pgvector + FTS) ──▶ JSON export + semantic/keyword search
```

---

## What's in here

| File / dir | Purpose |
|---|---|
| `katbook_vip_poc.ipynb` | **The pipeline** — upload to Kaggle and run. This is the engine. |
| `katbook_vip_poc.py` | Editable source mirror of the notebook (jupytext-style). |
| `export_results.py` | Pull every video's result from Postgres → `results/*.json` on your laptop. |
| `search.py` | Query the videos by meaning/keyword from your laptop (no GPU). |
| `requirements-local.txt` | The two small libraries the laptop tools need. |
| `docs/ARCHITECTURE.md` | Pipeline diagram, components, data model, data flow. |
| `docs/OPERATIONS.md` | Runbook: how to run, monitor, troubleshoot. |
| `docs/ROADMAP.md` | POC → production maturity path. |

---

## How it operates — the flow

1. **Input** — videos live in a Kaggle dataset. The pipeline **auto-discovers** every `.mp4`; no
   path editing.
2. **Process** — for each video, 6 stages run on Kaggle's GPU, loading→using→freeing each model so
   a 16 GB T4 never overflows. The LLM fuses transcript + visual + NLP signals into strict JSON tags.
3. **Store** — results are written to **cloud Postgres** (`videos` + `segments`), with a stable
   `video_id` so re-runs **update instead of duplicate**. Postgres is the single source of truth.
4. **Use** — from your laptop, `export_results.py` pulls clean per-video JSON, and `search.py`
   (or the notebook's Gradio UI) finds the exact segment that answers a question.

Full diagram + data model: **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**.

---

## Quickstart (the recommended POC run)

**One-time setup** (~15 min): a free [Neon](https://neon.tech) Postgres, a HuggingFace token, and a
Kaggle account. Details in **[docs/OPERATIONS.md](docs/OPERATIONS.md)**.

1. **Upload** `katbook_vip_poc.ipynb` to Kaggle (**File → Import Notebook**).
2. **Settings:** GPU **T4 ×2**, Internet **On**. **Secrets:** `DATABASE_URL`, `HF_TOKEN`.
   **Add Input:** your video dataset.
3. **Cell 0:** set `CONFIG["PROCESS"]` — `"all"`, `"first"`, or a **number** to pick one video
   from the printed list. Leave `FAST_MODE=True` (≈ 4 min/video).
4. **Save Version → "Save & Run All (Commit)".** Close the tab — it runs headless (~12 h cap).
5. On your laptop, pull the results:
   ```bash
   pip install -r requirements-local.txt                  # once
   echo "postgresql://...your Neon url..." > db_url.txt    # once (gitignored)
   python export_results.py                                # -> results/*.json
   ```

> Want results to appear automatically while it runs? `python export_results.py --watch`.

### Query your videos (from the laptop, no GPU)
```bash
python search.py "time period of a pendulum"
python search.py "rational numbers" --subject Mathematics --k 5
python search.py "oscillation" --mode fts        # keyword-only (no ML libs needed)
```

---

## Run modes at a glance

| Goal | Use | Notes |
|---|---|---|
| **Reliable POC run** | Kaggle **Save & Run All (commit)** | headless, reproducible — **recommended** |
| Quick interactive check | Kaggle **Run All** | keep the tab open while it runs |

---

## Output example (one segment)

```json
{
  "segment": 1, "start": 0.0, "end": 150.0,
  "topic": "Simple Pendulum", "subject": "Physics", "grade": "High School",
  "difficulty": "beginner", "content_type": "lecture",
  "tags": ["simple pendulum", "time period", "oscillations", "bob", "string"],
  "summary": "Explains the mechanics of a simple pendulum and how its length affects the time period.",
  "confidence": 0.95, "dominant_scene": "animated visualization",
  "objects_detected": ["clock", "tv"]
}
```

---

## Notes
- **POC model swaps** (to fit a free T4): Qwen3-32B → Qwen2.5-7B 4-bit, plus FAST_MODE lighter
  Whisper/CLIP/YOLO. Same architecture, smaller models. See [docs/ROADMAP.md](docs/ROADMAP.md).
- **Data is durable.** Everything lives in Postgres; Kaggle sessions ending never lose results.
- **Secrets** (`db_url.txt`) are gitignored — never committed.
