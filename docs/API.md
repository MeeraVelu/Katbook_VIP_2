# API reference (for the frontend)

Base URL: `http://<host>:8000` · Versioned prefix: `/api/v1` · OpenAPI/Swagger:
`GET /docs` · schema: `GET /openapi.json`.

The backend process contains **no UI** — it is a REST API only. A bundled static
operator console (nginx, no build step) ships separately in [`ui/`](../ui/README.md)
(compose `ui` service, default http://localhost:8080) and talks to this API purely
over HTTP; your production frontend is likewise an independent HTTP client. Keep
each client's origin in `CORS_ORIGINS`.

## Auth & CORS contract

- **Auth**: send header `X-API-Key: <API_KEY>` on every `/api/v1/*` request. The
  key is the server's `API_KEY` env value. If `API_KEY` is unset the API runs with
  auth **disabled** (dev only). `/health` and `/ready` need no key.
- **CORS**: the server allows the origins listed in `CORS_ORIGINS` (comma-
  separated). Set it to your frontend's exact origin (e.g.
  `https://app.katbook.example`). Credentials are allowed; `X-Request-ID` is
  exposed.
- **Request IDs**: every response carries `X-Request-ID` (echoed if you send one).
  It appears in error envelopes and server logs — include it in bug reports.

## Error envelope

Every non-2xx response has this shape:

```json
{ "error": { "code": "not_found", "message": "No video ...",
             "request_id": "a1b2c3d4", "details": null } }
```

Codes: `bad_request` (400), `unauthorized` (401), `not_found` (404),
`validation_error` (422), `internal_error` (500), `unavailable` (503).

---

## Videos

### `POST /api/v1/videos` — register a server-side path
Runs the SHA-256 dedup pre-check **before** enqueueing.

```bash
curl -X POST http://localhost:8000/api/v1/videos \
  -H "X-API-Key: $API_KEY" -H 'Content-Type: application/json' \
  -d '{"source_path":"/data/inbox/lesson.mp4","force":false}'
```
```json
{ "job_id":"3f2...","video_id":"9ab...","status":"queued",
  "dedup":{"is_duplicate":false,"canonical_video_id":null,"content_hash":"...","reason":"new content"},
  "message":"Queued for processing." }
```
`status` ∈ `queued` | `duplicate` (byte-identical; `job_id:null`) | `exists`
(already processed; pass `force:true` to reprocess).

### `POST /api/v1/videos/upload` — multipart upload to the inbox
```bash
curl -X POST http://localhost:8000/api/v1/videos/upload \
  -H "X-API-Key: $API_KEY" -F 'file=@lesson.mp4' -F 'force=false'
```
Same response as above (the file is saved to the inbox, then registered).

### `POST /api/v1/videos/batch` — enqueue a folder/glob (the 95k backlog)
```bash
curl -X POST http://localhost:8000/api/v1/videos/batch \
  -H "X-API-Key: $API_KEY" -H 'Content-Type: application/json' \
  -d '{"folder":"/data/inbox"}'          # or {"glob":"/data/inbox/**/*.mp4"}
```
```json
{ "enqueued":128,"duplicates":0,"skipped_existing":4,"total":132,"items":[...] }
```

### `GET /api/v1/videos` — paginated list with filters
Query params: `page`, `page_size`, `subject`, `grade_level`, `language`,
`has_speech`, `status`, `include_deleted`.
```bash
curl "http://localhost:8000/api/v1/videos?page=1&page_size=25&subject=Mathematics&has_speech=true" \
  -H "X-API-Key: $API_KEY"
```
```json
{ "items":[{"video_id":"...","source_path":"...","status":"done","language":"en",
            "has_speech":true,"tagging_path":"voice","duration_sec":612.0,
            "segment_count":8,"is_duplicate":false,"created_at":"..."}],
  "page":1,"page_size":25,"total":1 }
```

### `GET /api/v1/videos/{video_id}` — full record + segments
```bash
curl http://localhost:8000/api/v1/videos/9ab... -H "X-API-Key: $API_KEY"
```
Returns the video fields plus `rollup` (majority subject/grade, primary topic,
topics, all_tags) and `segments[]` (each with topic/subject/grade_level/
difficulty/content_type/tags/subtopics/summary/confidence/transcript_text/ocr and
silent-path scenes/objects/captions).

### `DELETE /api/v1/videos/{video_id}` — soft-delete only
```bash
curl -X DELETE http://localhost:8000/api/v1/videos/9ab... -H "X-API-Key: $API_KEY"
```
Sets `status='soft_deleted'`. **Content and segments are retained** (safety rule:
nothing is ever hard-deleted or auto-merged).

## Jobs

### `GET /api/v1/jobs/{job_id}` — status + live stage + timings
```bash
curl http://localhost:8000/api/v1/jobs/3f2... -H "X-API-Key: $API_KEY"
```
```json
{ "job_id":"3f2...","video_id":"9ab...","state":"processing",
  "current_stage":"visual","attempts":1,
  "stage_timings":{"ingest_audio":0.4,"transcribe":8.1,"extract_frames":1.2},
  "elapsed_sec":11.9,"error":null,"enqueued_at":"...","started_at":"...","finished_at":null }
```
`state` ∈ `queued` | `processing` | `done` | `failed`.

## Search

### `GET /api/v1/search` — semantic | keyword | hybrid
Query params: `q` (required), `mode` (`semantic` default | `keyword` | `hybrid`),
`limit` (1–100).
```bash
curl "http://localhost:8000/api/v1/search?q=time+period+of+a+pendulum&mode=hybrid&limit=10" \
  -H "X-API-Key: $API_KEY"
```
```json
{ "query":"time period of a pendulum","mode":"hybrid","count":3,
  "results":[{"video_id":"...","seg_index":2,"start_sec":120.0,"end_sec":180.0,
              "topic":"Simple Pendulum","subject":"Physics","score":0.031}] }
```
- `semantic`: pgvector cosine over BGE-M3 segment embeddings.
- `keyword`: Postgres FTS over `transcript_text + summary + topic`.
- `hybrid`: Reciprocal Rank Fusion of both (fused `score`).
- If the query-embedding service is unavailable, `semantic`/`hybrid` transparently
  return `keyword` results (the response `mode` reflects what actually ran).

## Health

- `GET /health` — liveness `{"status":"ok","version":"3.0.0"}` (no auth).
- `GET /ready` — readiness; `200` when DB + Redis + worker GPU heartbeat are all
  good, else `503` with a per-check breakdown.
