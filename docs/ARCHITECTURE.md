# Architecture & Data Flow

Katbook VIP turns a raw lecture video into **searchable, structured knowledge**: per-segment
topics, subjects, grade levels, tags, summaries, plus embeddings for semantic search.

## The 6-stage pipeline

```
            ┌─────────────────────────── one video ───────────────────────────┐
            │                                                                  │
  Stage 1   │  INGEST / DEMUX        ffmpeg → 16 kHz mono WAV + sampled frames │
            │                                                                  │
  Stage 2A  │  AUDIO                 faster-whisper (transcript)               │
            │                        librosa (energy / silence / WPM)          │
            │                        [pyannote diarization — full quality]     │
            │                                                                  │
  Stage 2B  │  VISUAL (per frame)    CLIP   → scene label                      │
            │                        YOLOv8 → objects                          │
            │                        EasyOCR→ on-screen text                   │
            │                        [BLIP-2 → captions — full quality]        │
            │                                                                  │
  Stage 3   │  NLP                   spaCy NER, keywords, MiniLM embeddings,   │
            │                        BERTopic                                  │
            │                                                                  │
  Stage 5   │  SEGMENTATION          cosine-drop on window embeddings + kneed  │
            │                        → coherent time segments                  │
            │                                                                  │
  Stage 4   │  LLM FUSION            Qwen2.5-7B (4-bit) reads transcript +     │
            │                        visual + nlp signals per segment          │
            │                        → strict JSON: topic/subject/grade/tags…  │
            │                                                                  │
  Stage 6   │  STORAGE               Postgres: videos + segments               │
            │                        embedding=vector, fts=tsvector, llm=jsonb │
            │                        (+ local Qdrant demo)                     │
            └──────────────────────────────────────────────────────────────────┘
```

Every heavy model is **loaded → used → freed** (`free_vram`) between stages, so a single 16 GB
T4 never overflows. In batch mode the small embedder is loaded once for the whole run; the
heavy models reload per stage per video.

## Component map

| Concern | POC implementation | File / location |
|---|---|---|
| Orchestration | sequential Python (`process_video` loop) | notebook Cell 3b |
| Compute | Kaggle T4×2 (free) | `katbook_vip_poc.ipynb` |
| Transcription | faster-whisper (`medium`/`large-v3`) | pipeline |
| Vision | CLIP, YOLOv8, EasyOCR, BLIP-2 | pipeline |
| LLM tagging | Qwen2.5-7B-Instruct, 4-bit (bitsandbytes) | pipeline |
| Embeddings | sentence-transformers MiniLM (384-d) | pipeline |
| Durable store | **cloud Postgres** + `pgvector` + `tsvector` | Neon/Supabase |
| Vector store (demo) | Qdrant local mode | `/kaggle/working/qdrant_db` |
| Results export | DB → per-video JSON | `export_results.py` |
| Search | semantic (pgvector) + keyword (FTS) + tag filters | `search.py`, notebook Cell 14 |

## Data model (Postgres)

```
videos
  video_id UUID PK        -- uuid5(file_path): stable, so re-runs UPSERT (no duplicates)
  source_path TEXT
  duration FLOAT
  language TEXT
  audio_features JSONB
  nlp JSONB
  stage_timings JSONB
  created_at TIMESTAMPTZ

segments
  id SERIAL PK
  video_id UUID FK -> videos
  seg_index INT
  start_sec, end_sec FLOAT
  transcript TEXT
  scenes JSONB, objects JSONB, ocr TEXT
  llm JSONB              -- topic/subtopics/difficulty/grade_level/subject/summary/tags/...
  embedding VECTOR(384)  -- pgvector, cosine
  fts TSVECTOR           -- generated from transcript, GIN-indexed
```

## End-to-end flow

```
   videos ──> [ PIPELINE on GPU ] ──> Postgres (durable) ──┬──> export_results.py ──> results/*.json
 (dataset)     Kaggle OR Docker          (videos+segments) │
                                                           └──> search.py / Gradio UI ──> ranked segments
```

The database is the **single source of truth**. Everything downstream (local JSON files, the
search UI, future APIs) reads from Postgres — so results survive any Kaggle session ending.

See [ROADMAP.md](ROADMAP.md) for how each box hardens into a production service.
