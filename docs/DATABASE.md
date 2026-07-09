# Database

PostgreSQL 16 + [pgvector](https://github.com/pgvector/pgvector) is the single
datastore: relational (`videos` → `segments` → `jobs`), semantic search (pgvector
cosine), keyword search (tsvector FTS), and exact-duplicate lookups all live in
**one** engine. Image: `pgvector/pgvector:pg16`. Schema is owned by **Alembic**
(`database/versions/` — `0001_initial_schema.py`, `0002_enrich_schema.py`,
`0003_cleanup_segments.py`) — no runtime `CREATE TABLE`.

## Why Postgres + pgvector (not a dedicated vector DB)

At this scale (95k videos → ~1M segments) a separate vector database (Pinecone,
Milvus, Qdrant, …) would add an extra service, a second consistency boundary, and
network hops — while gaining little. pgvector gives us:

- **One transaction** across the relational record, the embedding, and the FTS
  index — no dual-write drift between "the row" and "its vector".
- **Hybrid search in-engine**: cosine (`<=>`) and `tsvector` FTS fused with RRF in
  SQL, no cross-service join.
- **Operational simplicity**: one thing to back up, secure, and monitor.
- **Ample headroom**: ~1M rows of 1024-d vectors with HNSW is comfortable for a
  single well-provisioned Postgres.

If the corpus grows 10–100×, revisit (partitioning, IVF, or an external ANN store).

## Schema

```mermaid
erDiagram
    videos ||--o{ segments : has
    videos ||--o{ jobs : tracked_by
    videos ||--o| videos : canonical_of

    videos {
        uuid video_id PK
        text source_path
        text video_filename "basename(source_path), denormalized"
        text content_hash "sha256 (dedup)"
        bigint file_size_bytes
        double duration_sec
        text language
        boolean has_speech
        text tagging_path "voice|silent"
        text profile "KVIP_PROFILE this video ran under"
        text status "queued|processing|done|failed|soft_deleted"
        boolean is_duplicate
        uuid canonical_video_id FK
        text error_message
        jsonb runtime
        jsonb stage_timings
        timestamptz created_at
        timestamptz updated_at
    }
    segments {
        uuid segment_id PK
        uuid video_id FK
        int seg_index
        double start_sec
        double end_sec
        real est_min "opportunistic"
        text topic
        text subject
        text grade_level
        text difficulty
        text content_type
        text bloom_level "opportunistic"
        text knowledge_type "reserved"
        jsonb learning_objectives "opportunistic"
        jsonb prerequisites "reserved (no curriculum context)"
        text aku_id "reserved"
        text_array tags
        text_array subtopics
        text summary
        double confidence
        boolean review_flag "confidence<0.5 or LLM-recovery path"
        text transcript_text
        text ocr
        text dominant_scene "most frequent per-frame scene label"
        jsonb speakers "[{role, language}], opportunistic"
        jsonb objects "detected objects, sole source of truth"
        jsonb extra "scenes/captions/has_visual_content ONLY (no dedicated-column dupes)"
        vector embedding "1024-d (BGE-M3)"
        tsvector fts "generated, incl. ocr"
        timestamptz created_at
    }
    jobs {
        uuid job_id PK
        uuid video_id FK
        text video_filename "denormalized"
        text state "queued|processing|done|failed|dead_letter"
        text current_stage
        text error_stage "best-effort: stage at time of failure"
        int attempts
        jsonb stage_timings
        text error
        int progress_pct "0-100"
        text profile "KVIP_PROFILE this job ran under"
        real health_score "reserved"
        timestamptz enqueued_at
        timestamptz started_at
        timestamptz finished_at
    }
```

Notes on the design vs the POC:
- `segments` uses **typed columns** (topic/subject/grade_level/…) for clean
  filtering + search, replacing the POC's `llm` JSONB blob. The non-core LLM
  fields (speaker_role, language, subject_raw, recovery flags) and the visual
  signals (scenes/objects/captions) are kept in `extra` (jsonb) and `ocr`, so the
  exact per-video export JSON is reconstructable **losslessly**.
- `fts` is a **generated** `tsvector` over `transcript_text || summary || topic`.
- Deletes are **soft** (`status='soft_deleted'`). Only byte-identical files are
  ever deduplicated (`is_duplicate` + `canonical_video_id`); same-topic/
  different-content videos are never merged or removed.

## Handling Duplicate Uploads

Three scenarios, driven by `video_id = uuid5(source_path)` (deterministic per
file path) plus a SHA-256 `content_hash` pre-check, both computed in
`api/services/videos.py::register_video`:

**A) Fresh upload (not a duplicate)**
New `source_path` → new `video_id`, and its `content_hash` doesn't match any
other video. Registered as `status='queued'`, `is_duplicate=FALSE`,
`canonical_video_id=NULL`, and enqueued for processing normally.

**B) Byte-identical duplicate found**
A *different* `source_path` (so a different `video_id`) hashes to the exact
same `content_hash` as an existing, already-processed video. The new row is
recorded as `is_duplicate=TRUE`, `canonical_video_id=<the original's
video_id>`, `status='done'` — **no processing runs**, no GPU time spent
re-tagging content that's byte-for-byte identical. The API returns **409
Conflict** with the canonical video's id/segment count/timestamp so the
caller can look at the existing results instead. Passing `force=true`
bypasses this check entirely and processes the upload independently anyway
(useful for deliberately re-running the latest models/prompts against
content you know is unchanged).

**C) Force reprocess of an existing video**
Same `source_path` → same `video_id`, uploaded again with `force=true`. No
new video row — the *same* `video_id` is reset to `status='queued'` and a
new `jobs` row is created. When the run completes, `pipeline/storage.py`'s
`store()` unconditionally does `DELETE FROM segments WHERE video_id=...`
before inserting the fresh segments, and `UPDATE`s the `videos` row in
place — so segment count stays the same but every `segment_id` is a fresh
UUID, and `videos.updated_at` (and the `segments_set_updated_at` trigger)
reflect the new run. Without `force=true`, re-registering an already-`done`
`video_id` short-circuits with the same 409 as scenario B, instead of
silently no-oping.

## Indexes

| Index | Column | Purpose |
|---|---|---|
| `segments_embedding_hnsw` | `embedding` (HNSW, `vector_cosine_ops`, m=16, ef_construction=64) | semantic search |
| `segments_fts_idx` | `fts` (GIN) | keyword search |
| `segments_video_id_idx` | `video_id` | fetch a video's segments; cascade delete |
| `segments_subject_idx`, `segments_grade_idx` | `subject`, `grade_level` | list-endpoint filters |
| `videos_content_hash_idx` | `content_hash` | O(log n) dedup lookup |
| `videos_status_idx` | `status` | list filter / queue scans |

### HNSW over IVFFlat

- **No training step.** IVFFlat needs a populated table to build lists (`lists`
  parameter) and degrades if data distribution shifts as the backlog loads.
  HNSW is incremental — build the index once, insert as you go.
- **Better recall/latency** at ~1M rows for our query pattern (top-k per query).
- **Tunable at query time** without a rebuild via `hnsw.ef_search`.

Build parameters: `m = 16` (graph degree) and `ef_construction = 64` are a solid
default for ~1M rows; raise `ef_construction` (e.g. 128) for higher build-time
recall at the cost of index build time.

### Tuning `ef_search`

Recall vs latency is controlled per query by `hnsw.ef_search` (default set by the
API via `HNSW_EF_SEARCH`, applied as `SET LOCAL hnsw.ef_search = N` inside the
search transaction):

```sql
SET hnsw.ef_search = 40;    -- faster, lower recall
SET hnsw.ef_search = 100;   -- slower, higher recall
```

Start at 80; increase if users report missing obvious matches, decrease if search
latency is the bottleneck.

## Capacity math (95k videos)

- 95,000 videos × ~8–12 segments ≈ **0.8–1.1M segment rows**.
- Embedding: 1024 dims × 4 bytes = **4 KB/vector** → ~4 GB of raw vectors for 1M
  rows; the HNSW index adds roughly 1.5–2× on top (graph links) → budget
  **~10–12 GB** for vectors + index.
- Text (transcript/summary/ocr) + FTS: dominated by transcripts; budget a few GB.
- Total: a **50–100 GB** data volume is comfortable with headroom. Provision the
  `pgdata` volume accordingly and keep `shared_buffers`/`work_mem` tuned for the
  host RAM.

## First-time setup

The compose `migrate` service runs this automatically before `api`/`worker`. To do
it by hand:

```bash
# 1) bring up Postgres (compose) or point DATABASE_URL at your instance
docker compose up -d postgres

# 2) apply migrations (creates the vector extension, tables, indexes)
export DATABASE_URL=postgresql://katbook:change-me-strong@localhost:5432/katbook
export KVIP_EMBED_DIM=1024          # must match your embedder (BGE-M3 = 1024)
alembic upgrade head

# verify
psql "$DATABASE_URL" -c "\d+ segments"
psql "$DATABASE_URL" -c "SELECT indexname FROM pg_indexes WHERE tablename='segments';"
```

> The embedding column width comes from `KVIP_EMBED_DIM` at migration time and is
> validated against the configured embedder at pipeline startup (fail-fast on
> mismatch). If you switch embedders, create a new migration and run
> `scripts/reembed.py`.

## Backup & restore

```bash
# backup (dated, compressed)
DATABASE_URL=postgresql://katbook:...@host:5432/katbook ./scripts/backup.sh ./backups
# or inside compose:
docker compose exec -T postgres pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" | gzip > backup.sql.gz

# restore into a fresh database
gunzip -c katbook_2026-07-04_120000.sql.gz | psql "$DATABASE_URL"
```

Keep backups **off-box** (object storage), and periodically test a restore into a
throwaway database. The `pgdata` Docker volume is the live store — snapshot the
underlying disk as well if your host supports it.

## Legacy 384-d data

POC rows used MiniLM (384-d) vectors, which are dimensionally incompatible with
the production `vector(1024)` column. If you import legacy text, run:

```bash
python scripts/reembed.py            # embeds rows with NULL embeddings
python scripts/reembed.py --all      # re-embed everything (after an embedder change)
```
