# Katbook Video Intelligence Platform (VIP)

Turns lecture / animation videos into **per-segment structured tags** — topic,
subject, grade level, difficulty, tags, summary, plus a vector embedding — and
stores them in Postgres so you can search your whole video library by *meaning*
or by keyword.

Built to run on a **free Kaggle T4 GPU**, loading **one model into VRAM at a
time**, and to handle **both narrated and silent videos in any language**.

```
video → voice/silent router → transcribe (any lang) → adaptive frames
      → CLIP scenes + gated YOLO/OCR + BLIP-2 captions → segment
      → Qwen tags each segment → Postgres (+ results/*.json)
```

## Repo layout

```
katbook_vip/            the importable pipeline package (edit this in VS Code)
  config.py             one CONFIG dict + fast/balanced/quality profiles
  run.py                discover videos, select, run the batch  (entry point)
  pipeline.py           process ONE video end-to-end, with per-stage timing
  router.py             decide VOICE vs SILENT path
  ingest.py             ffmpeg: duration, audio extract, adaptive frame plan
  audio.py              speech detection (RMS gate) + Whisper transcription
  visual.py             CLIP scenes, gated YOLO, gated OCR, BLIP-2 captions
  nlp_stage.py          spaCy NER + KeyBERT keyphrases + embeddings
  segment.py            voiced (cosine-drop) & silent (scene-group) segmentation
  tagging.py            Qwen per-segment tags + cross-segment consistency pass
  storage.py            idempotent upsert into Postgres (pgvector + FTS)
  export.py             write the clean results/<name>.json
  utils.py              managed_model() — guarantees one-model-at-a-time + VRAM free

katbook_vip_kaggle.ipynb   thin runner: install → clone package → set CONFIG → run
sync_results.py            LAPTOP: mirror Postgres results into ./results (--watch)
search.py                  LAPTOP: semantic + keyword search over the DB
requirements-local.txt     laptop-only deps (no GPU/ML) for the two scripts above
docs/ARCHITECTURE.md       how/why the pipeline is built the way it is
docs/OPERATIONS.md         run it on Kaggle, sync locally, troubleshoot
```

## Quick start

**On Kaggle (processing):**
1. New Notebook → Settings → Accelerator → **GPU T4 x2**.
2. Add Secrets: `DATABASE_URL` (your Neon/Supabase URL, required to store),
   `HF_TOKEN` (optional).
3. Add your videos as a Kaggle **Dataset** (any folder of `.mp4`).
4. Open `katbook_vip_kaggle.ipynb`, set `REPO_URL` to your repo, edit `CONFIG`
   (profile + which videos), **Run All**.

**On your laptop (reading results):**
```bash
pip install -r requirements-local.txt
set DATABASE_URL=postgresql://user:pass@host/db      # or put it in db_url.txt
python sync_results.py --watch                        # results/ fills in by itself
python search.py "time period of a pendulum"
```

See **docs/OPERATIONS.md** for the full runbook and **docs/ARCHITECTURE.md** for
the design (voice/silent routing, the speed wins, one-model-at-a-time).
