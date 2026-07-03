# ui/ — Katbook VIP console

A **self-contained, no-build** admin console (plain `index.html` + `app.js` +
`styles.css`, zero dependencies) served as its own nginx container. It talks to
the backend **only over the REST API** — the API process itself still loads no UI.

What it does:
- **Videos** — paginated list with filters (subject / grade / language /
  has_speech / status); click *View* for the full record + segments; soft-delete.
- **Search** — semantic / keyword / hybrid over segments.
- **Enqueue** — register a server path, upload a file, or enqueue a folder/glob.
- **Jobs** — enter a `job_id` and watch the live stage + timings until done/failed.

## Run it

Via compose (default, http://localhost:8080):

```bash
docker compose up -d ui
```

Or open `index.html` directly in a browser during development. Either way, set the
**API base URL** and **X-API-Key** in the top bar (persisted in `localStorage`).

## Requirements
- The API's `CORS_ORIGINS` must include this console's origin (e.g.
  `http://localhost:8080`) — it's in `.env.example` by default.
- If the API has `API_KEY` set, enter the same key in the console's top bar.

> This is an internal operator tool: the API key is stored client-side in
> `localStorage`. Serve it on a trusted network / behind your own auth if exposed.
