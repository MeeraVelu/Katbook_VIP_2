# Video Intelligence Pipeline — API Reference

Verified against the live route table (`api/routers/*.py`) on 2026-07-09 — every
endpoint below actually exists in code; nothing here is aspirational.

## Base URL

```
Local (Docker, CPU dev):   http://localhost:8000
Production (GPU box):      http://<GPU-BOX-IP>:8000
```

## Authentication

Every endpoint under `/api/v1/*` requires an `X-API-Key` header, checked against
the `API_KEY` environment variable (`api/deps.py::require_api_key`). Example
value in this dev environment: `change-me-api-key` (from `.env`).

- If `API_KEY` is **unset** in the environment, auth is disabled entirely (dev
  convenience) and the header is ignored.
- `GET /health` and `GET /ready` require **no auth** — they're liveness/readiness
  probes for orchestration.
- `GET /api/v1/videos/{video_id}/stream` is the one exception among the
  `/api/v1/*` routes: it's **not** behind the router-wide `X-API-Key` header
  check, because an HTML `<video>` element can't send custom headers. It
  accepts the key as **either** the `X-API-Key` header **or** a `?key=` query
  parameter.

Missing/wrong key on a protected route → `401 Unauthorized`.

## Error format

Every non-2xx response (except raw 401s from the auth layer) uses one envelope:

```json
{
  "error": {
    "code": "not_found",
    "message": "No video 5567163b-50d0-50fd-91c8-7b9bbcc749d4",
    "request_id": "6720b0d38bd34787",
    "details": null
  }
}
```

`code` → HTTP status mapping: `not_found`→404, `duplicate`→409,
`validation_error`→422, `bad_request`→400, `internal_error`→500. See
`api/errors.py`.

---

## Health & Status

### 1. Health Check

| | |
|---|---|
| Method | `GET` |
| URL | `http://localhost:8000/health` |
| Auth | None |
| Description | Cheap liveness probe — is the process up? |

**Response `200`**
```json
{ "status": "ok", "version": "3.0.0" }
```

### 2. Readiness Check

| | |
|---|---|
| Method | `GET` |
| URL | `http://localhost:8000/ready` |
| Auth | None |
| Description | Are dependencies actually reachable — Postgres, Redis, and (if `READY_REQUIRES_GPU=1`) a recent worker GPU heartbeat? |

**Response `200`** (ready — actual response from this CPU dev environment, `READY_REQUIRES_GPU=0`; `checks.worker_gpu` only appears when `READY_REQUIRES_GPU=1`)
```json
{
  "ready": true,
  "checks": { "database": true, "redis": true },
  "details": { "gpu": { "tier": "cpu", "device": null, "vram_gb": null, "capability": null, "cuda": false, "source": "cpu" } }
}
```

**Response `503`** (not ready — note the field is `checks`, not top-level booleans; shape shown here is a GPU deployment with `READY_REQUIRES_GPU=1`)
```json
{
  "ready": false,
  "checks": { "database": false, "redis": true, "worker_gpu": true },
  "details": { "database_error": "connection refused" }
}
```

---

## Video Ingestion

### 3. Register Video by Server Path

| | |
|---|---|
| Method | `POST` |
| URL | `http://localhost:8000/api/v1/videos` |
| Headers | `X-API-Key: change-me-api-key`<br>`Content-Type: application/json` |
| Description | Register a video file already visible inside the API container's `/data/inbox` volume. Runs a SHA-256 dedup pre-check before enqueueing. |

**Request Body**
```json
{
  "source_path": "/data/inbox/physics_video.mp4",
  "force": false
}
```
`force` (optional, default `false`): reprocess even if this exact path was
already processed, **and** bypass the byte-identical-content dedup check.

**Response `202`** (queued)
```json
{
  "job_id": "b4cd89f3-635a-4ba7-a4a5-206d7a26397f",
  "video_id": "5567163b-50d0-50fd-91c8-7b9bbcc749d4",
  "status": "queued",
  "dedup": {
    "is_duplicate": false,
    "canonical_video_id": null,
    "content_hash": "e32f857bb77631e8d2af3a8994c7f42f6d4d2f45f423c4f338dbd93f45f0748a",
    "reason": "new content"
  },
  "message": "Queued for processing."
}
```

**Response `409`** (already processed — same path, or byte-identical to another video; not sent when `force=true`)
```json
{
  "error": {
    "code": "duplicate",
    "message": "This video was already processed. Check 'Force reprocess if already done' to run it again with the latest models and prompts.",
    "request_id": "3e47b0a111d040db",
    "details": {
      "status": "duplicate",
      "existing_video_id": "5567163b-50d0-50fd-91c8-7b9bbcc749d4",
      "existing_segment_count": 4,
      "processed_at": "2026-07-09T05:59:51.651361+00:00"
    }
  }
}
```

**Response `404`** (path not found on the API container's filesystem)
```json
{ "error": { "code": "not_found", "message": "No file at '/data/inbox/missing.mp4'", "request_id": "...", "details": null } }
```

### 4. Upload Video File

| | |
|---|---|
| Method | `POST` |
| URL | `http://localhost:8000/api/v1/videos/upload` |
| Headers | `X-API-Key: change-me-api-key`<br>`Content-Type: multipart/form-data` (Postman sets this automatically for form-data bodies — do not set it by hand) |
| Description | Upload a file straight from browser/client into the shared inbox, then register it (same dedup logic as #3). |

**Request (form-data)**

| Key | Type | Value |
|---|---|---|
| `file` | File | the video binary |
| `force` | Text | `false` |

**Response `202`** — identical shape to #3.
**Response `409`** — identical shape to #3.

### 5. Enqueue Folder / Glob (Batch)

| | |
|---|---|
| Method | `POST` |
| URL | `http://localhost:8000/api/v1/videos/batch` |
| Headers | `X-API-Key: change-me-api-key`<br>`Content-Type: application/json` |
| Description | Sweep a whole directory (recursive) or a glob pattern and enqueue every unprocessed video in one call. Provide `folder` OR `glob`, not both. Per-file duplicates are skipped silently (no per-item 409 — this is a bulk endpoint), reflected in the response counts. |

**Request Body**
```json
{
  "folder": "/data/inbox",
  "glob": null,
  "force": false
}
```

**Response `202`**
```json
{
  "enqueued": 12,
  "duplicates": 0,
  "skipped_existing": 3,
  "total": 15,
  "items": [
    {
      "source_path": "/data/inbox/lesson1.mp4",
      "video_id": "4cb2f037-ea4b-5144-95e0-aac03aebc7e7",
      "job_id": "b4cd89f3-635a-4ba7-a4a5-206d7a26397f",
      "status": "queued",
      "is_duplicate": false
    }
  ]
}
```

---

## Video Data

### 6. List Videos

| | |
|---|---|
| Method | `GET` |
| URL | `http://localhost:8000/api/v1/videos?page=1&page_size=25` |
| Headers | `X-API-Key: change-me-api-key` |
| Description | Paginated video library with structured filters. |

**Query Parameters** (all optional except none are required)

| Param | Type | Default | Notes |
|---|---|---|---|
| `page` | int | 1 | |
| `page_size` | int | 25 | capped at 200 |
| `subject` | string | — | case-insensitive partial match, e.g. `phys` matches `Physics` |
| `grade_level` | string | — | case-insensitive partial match |
| `language` | string | — | case-insensitive partial match |
| `has_speech` | bool | — | |
| `status` | string | — | `queued` \| `processing` \| `done` \| `failed` \| `soft_deleted` |
| `include_deleted` | bool | false | |

**Response `200`**
```json
{
  "items": [
    {
      "video_id": "5567163b-50d0-50fd-91c8-7b9bbcc749d4",
      "source_path": "/data/inbox/physics_video.mp4",
      "status": "done",
      "language": "en",
      "has_speech": true,
      "tagging_path": "voice",
      "duration_sec": 394.0,
      "file_size_bytes": 54986655,
      "is_duplicate": false,
      "canonical_video_id": null,
      "segment_count": 4,
      "created_at": "2026-07-09T00:45:38.364192Z",
      "updated_at": "2026-07-09T06:16:23.926229Z"
    }
  ],
  "page": 1,
  "page_size": 25,
  "total": 3
}
```

### 7. Get Facets (filter dropdown options)

| | |
|---|---|
| Method | `GET` |
| URL | `http://localhost:8000/api/v1/videos/facets` |
| Headers | `X-API-Key: change-me-api-key` |
| Description | Distinct subject/grade/language values currently in the (non-deleted) library — powers Library page filter autocomplete. **Note: no `difficulty` facet exists** despite the field being on segments. |

**Response `200`**
```json
{
  "subjects": ["General Knowledge", "Mathematics", "Physics"],
  "grades": ["Grade 1-2"],
  "languages": ["en"]
}
```

### 8. Get Video Details

| | |
|---|---|
| Method | `GET` |
| URL | `http://localhost:8000/api/v1/videos/{video_id}` |
| Example | `http://localhost:8000/api/v1/videos/5567163b-50d0-50fd-91c8-7b9bbcc749d4` |
| Headers | `X-API-Key: change-me-api-key` |
| Description | Full metadata for one video, plus a trimmed `segments` array (no `segment_id`, no enrichment columns — see #9 for the full-fidelity version) and a `rollup` (dominant subject/grade/difficulty across all segments). |

**Response `200`** (abridged)
```json
{
  "video_id": "5567163b-50d0-50fd-91c8-7b9bbcc749d4",
  "source_path": "/data/inbox/physics_video.mp4",
  "status": "done",
  "language": "en",
  "duration_sec": 394.0,
  "content_hash": "e32f857b...",
  "error_message": null,
  "stage_timings": { "ingest_audio": 1.26, "visual": 36.6, "llm": 0.0, "store": 1.02 },
  "runtime": { "os": "Linux ...", "gpu": null, "profile": "smoke" },
  "rollup": { "subject": "Physics", "grade": "Grade 1-2", "difficulty": "beginner", "primary_topic": "...", "topics": ["..."], "all_tags": ["..."] },
  "segments": [
    {
      "seg_index": 0, "start_sec": 0.0, "end_sec": 135.0,
      "topic": "Now Let Us Discuss", "subject": "Physics", "grade_level": "Grade 1-2",
      "difficulty": "beginner", "content_type": "lecture",
      "tags": ["..."], "subtopics": ["..."], "summary": "...",
      "confidence": 0.7, "transcript_text": "...", "ocr": "...",
      "scenes": ["text-heavy slide"], "objects": [], "captions": []
    }
  ]
}
```

**Response `404`** if `video_id` doesn't exist.

### 9. Get Video Segments (full-fidelity)

| | |
|---|---|
| Method | `GET` |
| URL | `http://localhost:8000/api/v1/videos/{video_id}/segments` |
| Example | `http://localhost:8000/api/v1/videos/5567163b-50d0-50fd-91c8-7b9bbcc749d4/segments` |
| Headers | `X-API-Key: change-me-api-key` |
| Description | Every column of every `segments` row for one video — includes `segment_id`, `bloom_level`, `knowledge_type`, `learning_objectives`, `prerequisites`, `aku_id`, `dominant_scene`, `speakers`, `objects`, `review_flag`, `est_min`, `created_at`, none of which appear in #8's trimmed list. |

**Response `200`**
```json
[
  {
    "segment_id": "9178e3b8-89eb-491f-a1c5-66d356e17823",
    "video_id": "5567163b-50d0-50fd-91c8-7b9bbcc749d4",
    "seg_index": 0, "start_sec": 0.0, "end_sec": 135.0,
    "est_min": 2.0, "topic": "...", "subject": "Physics", "grade_level": "Grade 1-2",
    "difficulty": "beginner", "content_type": "lecture",
    "bloom_level": "understand", "knowledge_type": "conceptual",
    "learning_objectives": ["Students will be able to describe ..."],
    "prerequisites": [], "aku_id": null,
    "tags": ["..."], "subtopics": ["..."], "summary": "...",
    "confidence": 0.7, "review_flag": false,
    "transcript_text": "...", "ocr": "...",
    "dominant_scene": "text-heavy slide",
    "speakers": [{ "role": "teacher", "language": "en" }],
    "objects": [], "scenes": ["text-heavy slide"], "captions": [],
    "has_visual_content": true,
    "created_at": "2026-07-09T06:16:23.926229Z"
  }
]
```

**Response `404`** if `video_id` doesn't exist.

### 10. Stream Video

| | |
|---|---|
| Method | `GET` |
| URL | `http://localhost:8000/api/v1/videos/{video_id}/stream` |
| Auth | `X-API-Key` header **or** `?key=` query param (see Authentication above) |
| Description | Streams the source video file from disk with HTTP Range support (206 Partial Content) so the browser `<video>` player can seek. Used as a `<video src>`, not typically opened directly in Postman. |

**Response `200`/`206`**: raw video bytes, `Content-Type` guessed from the file extension.
**Response `404`**: video not found, or the source file no longer exists on disk (`"Video file not available"`).
**Response `401`**: missing/wrong key (only when `API_KEY` is set).

### 11. Soft-Delete Video

| | |
|---|---|
| Method | `DELETE` |
| URL | `http://localhost:8000/api/v1/videos/{video_id}` |
| Headers | `X-API-Key: change-me-api-key` |
| Description | Sets `status='soft_deleted'` only — **never** deletes the row or its segments. Excluded from list/search by default (`include_deleted=true` on #6 to see it again). |

**Response `200`**
```json
{
  "video_id": "5567163b-50d0-50fd-91c8-7b9bbcc749d4",
  "status": "soft_deleted",
  "message": "Soft-deleted (status flag only; content and segments are retained)."
}
```

**Response `404`** if `video_id` doesn't exist.

---

## Job Tracking

### 12. List Active Jobs

| | |
|---|---|
| Method | `GET` |
| URL | `http://localhost:8000/api/v1/jobs/active` |
| Headers | `X-API-Key: change-me-api-key` |
| Description | Job(s) currently `state='processing'`. Normally 0 or 1 (worker `concurrency=1`), returned as a flat array — **not** split into `processing`/`queued` buckets. |

**Response `200`**
```json
[
  {
    "job_id": "b4cd89f3-635a-4ba7-a4a5-206d7a26397f",
    "video_id": "4cb2f037-ea4b-5144-95e0-aac03aebc7e7",
    "state": "processing",
    "current_stage": "visual",
    "attempts": 1,
    "stage_timings": { "ingest_audio": 1.26, "extract_frames": 0.78 },
    "error": null,
    "enqueued_at": "2026-07-09T06:12:00Z",
    "started_at": "2026-07-09T06:12:03Z",
    "finished_at": null,
    "elapsed_sec": 46.4,
    "video_filename": "test_video.mp4"
  }
]
```

### 13. List Job History

| | |
|---|---|
| Method | `GET` |
| URL | `http://localhost:8000/api/v1/jobs/history?page=1&page_size=25&status=done` |
| Headers | `X-API-Key: change-me-api-key` |
| Description | Completed (`done`) and/or `failed` jobs, most recently finished first. |

**Query Parameters**

| Param | Type | Default | Notes |
|---|---|---|---|
| `page` | int | 1 | |
| `page_size` | int | 25 | capped at 200 |
| `status` | string | both | `done` \| `failed` (any other value returns both) |

**Response `200`**
```json
{
  "items": [
    {
      "job_id": "b4cd89f3-635a-4ba7-a4a5-206d7a26397f",
      "video_id": "4cb2f037-ea4b-5144-95e0-aac03aebc7e7",
      "video_filename": "test_video.mp4",
      "status": "done",
      "subject": "Physics",
      "segment_count": 3,
      "processing_duration_sec": 85.3,
      "completed_at": "2026-07-09T06:16:23.926229Z",
      "error": null
    }
  ],
  "page": 1,
  "page_size": 25,
  "total": 1
}
```

### 14. Get Job Details

| | |
|---|---|
| Method | `GET` |
| URL | `http://localhost:8000/api/v1/jobs/{job_id}` |
| Example | `http://localhost:8000/api/v1/jobs/b4cd89f3-635a-4ba7-a4a5-206d7a26397f` |
| Headers | `X-API-Key: change-me-api-key` |
| Description | Live status of one job — same shape as an item in #12, minus `video_filename`. |

**Response `200`**
```json
{
  "job_id": "b4cd89f3-635a-4ba7-a4a5-206d7a26397f",
  "video_id": "4cb2f037-ea4b-5144-95e0-aac03aebc7e7",
  "state": "done",
  "current_stage": "done",
  "attempts": 1,
  "stage_timings": { "llm": 0.0, "nlp": 23.17, "store": 1.02, "visual": 36.6 },
  "error": null,
  "enqueued_at": "2026-07-09T06:12:00Z",
  "started_at": "2026-07-09T06:12:03Z",
  "finished_at": "2026-07-09T06:16:23Z",
  "elapsed_sec": 260.0
}
```

**Response `404`** if `job_id` doesn't exist.

---

## Search

### 15. Search Segments

| | |
|---|---|
| Method | `GET` |
| URL | `http://localhost:8000/api/v1/search?q=photosynthesis&mode=semantic&limit=10` |
| Headers | `X-API-Key: change-me-api-key` |
| Description | Semantic (pgvector cosine), keyword (Postgres FTS), or hybrid (Reciprocal Rank Fusion of both) search over segment content. Semantic/hybrid gracefully fall back to keyword-only if `EMBEDDINGS_URL` is unset or unreachable (as in this CPU dev environment). |

**Query Parameters**

| Param | Type | Default | Notes |
|---|---|---|---|
| `q` | string | — | **required**, min length 1 |
| `mode` | string | `semantic` | `semantic` \| `keyword` \| `hybrid` |
| `limit` | int | 10 | 1–100 |

**Response `200`**
```json
{
  "query": "photosynthesis",
  "mode": "keyword",
  "count": 2,
  "results": [
    {
      "video_id": "4cb2f037-ea4b-5144-95e0-aac03aebc7e7",
      "seg_index": 0,
      "start_sec": 0.0,
      "end_sec": 135.0,
      "topic": "Now Let Us Discuss",
      "subject": "General Knowledge",
      "grade_level": "Grade 1-2",
      "summary": "Auto stub summary for: Now Let Us Discuss.",
      "score": 0.87
    }
  ]
}
```
Note: `mode` in the response is the **actual** mode used, which can differ from
the requested `mode` (e.g. you asked for `semantic`, embeddings were
unavailable, so it silently ran `keyword` instead — check this field, don't
assume the request `mode` was honored).

**Response `422`** if `q` is missing or empty (standard FastAPI validation error envelope).

---

## Endpoints that do NOT exist

For anyone cross-checking against an earlier draft of this document or the UI's
apparent behavior — these were never implemented; don't add them to Postman:

- `GET /api/stats` — no system-stats endpoint exists.
- `GET /api/inbox` — no endpoint lists raw inbox filesystem contents; the
  closest equivalent is #6 (`GET /api/v1/videos`), which only shows
  **registered** videos, not raw files sitting in `/data/inbox`.
- `POST /api/videos/enqueue` — the real batch endpoint is `POST
  /api/v1/videos/batch` (#5).
- `GET /api/facets` — the real path is nested under videos:
  `GET /api/v1/videos/facets` (#7).
- A `difficulties` list in the facets response — `FacetsResponse` only has
  `subjects`/`grades`/`languages`.
