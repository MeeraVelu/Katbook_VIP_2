# ui/ — Katbook VIP console (React SPA)

The product's operator console: React 18 + TypeScript + Vite + Tailwind +
@tanstack/react-query + react-router-dom + lucide-react. No component library, no
CSS-in-JS. "Mission control" dark theme with one warm amber accent, muted cyan for
semantic-search surfaces. Fonts are self-hosted (`@fontsource`), no runtime CDN.

> This is the **default console**, not the only client. It talks to the backend
> purely over the documented REST API (`docs/API.md`), so an external frontend can
> replace it via the same API without touching the backend.

## Pages & signature components
- **Library** — filterable table → **VideoDetail** with the `SegmentTimeline`
  (blocks by subject, height by confidence) + segment cards with `ConfidenceRing`.
- **Search** — semantic / keyword / hybrid with fused-score bars (also via the
  `CommandBar`: press **`/`** anywhere).
- **Ingest** — upload / server-path / batch-glob → deep-links to the job.
- **Jobs** — in-flight board + **JobDetail** with the `PipelineStepper` (live,
  auto-polls until terminal).
- **System** — `/health` + `/ready` per-check breakdown + `GpuTierChip` tier.

## Run it

**Production (compose):** built by `docker/Dockerfile.ui` (node build → nginx) and
served at **http://localhost:${UI_PORT:-8080}**. nginx reverse-proxies `/api/*`,
`/health`, `/ready` to the `api` service **unchanged** (same-origin — no CORS), so
the browser only talks to this origin.

```bash
docker compose up -d ui
```

**Local dev:**
```bash
cd ui
npm install
npm run dev          # http://localhost:5173 ; vite proxies /api to VITE_API_TARGET
# point at a running API (default http://localhost:8000):
VITE_API_TARGET=http://localhost:8000 npm run dev
```

## Auth
Set the API key via the header key button (stored in `localStorage`, sent as
`X-API-Key` on every request). Leave blank if the API has auth disabled.

## Boundaries
- The API image contains **zero** UI code/deps.
- `src/lib/types.ts` mirrors the backend Pydantic schemas 1:1.
- `ui/node_modules` and `ui/dist` are gitignored build artifacts.
