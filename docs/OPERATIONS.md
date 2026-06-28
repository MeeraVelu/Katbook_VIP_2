# Operations Runbook

How to run, monitor, and troubleshoot the POC. Two ways to run — pick by goal.

## Run options (both use Kaggle's GPU; both write to the same Postgres)

| # | Method | When to use | Keeps running unattended? |
|---|---|---|---|
| **1** | **Kaggle → Save & Run All (commit)** | ✅ **Recommended** — reliable, reproducible | **Yes** (headless, ~12 h cap) |
| 2 | Kaggle → interactive Run All | quick checks while watching | No (session must stay open) |

> The VS Code↔Kaggle **tunnel** is a *development* convenience only. It dies when the Kaggle
> session stops, so do **not** use it for unattended runs. Use option 1.
>
> Running off-Kaggle (your own/cloud GPU) is a future step — see [ROADMAP.md](ROADMAP.md).

---

## Option 1 — Kaggle committed run (recommended)

**One-time setup** (see [../README.md](../README.md)): Neon Postgres, HF token, upload the
notebook, attach the dataset, add `DATABASE_URL` + `HF_TOKEN` secrets, GPU T4×2, Internet On.

**Each run:**
1. Open the notebook on kaggle.com.
2. In **Cell 0** set `CONFIG["PROCESS"]` — `"all"`, `"first"`, a **number** (pick one video by
   the printed list), or a filename substring.
3. **Save Version → "Save & Run All (Commit)" → Save.**
4. Close the tab. It runs in the background (≈4 min/video FAST_MODE).
5. When the version goes green, pull results on your laptop:
   ```bash
   python export_results.py        # DB -> results/*.json
   ```

**Live results while it runs:** start the watcher on your laptop first —
`python export_results.py --watch` — and JSONs appear as each video lands in Postgres.

---

## Pre-flight checklist (prevents 90% of failures)

- [ ] GPU = **T4 ×2**, **Internet = On**
- [ ] Secrets `DATABASE_URL` **and** `HF_TOKEN` attached
- [ ] Dataset attached → Cell 0 prints `Discovered N video(s)`
- [ ] `CONFIG["PROCESS"]` set to what you intend
- [ ] Using the **latest** notebook (batch-only, numpy-safe Cell 1)

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `torch has no attribute fx` on import | a dep downgraded numpy below the torch ABI | Cell 1 already restores base numpy; if it persists, **Factory reset** then run |
| `NameError: DATABASE_URL` | secret not loaded this session | run the secrets cell / set env; batch cell self-bootstraps it |
| `schema "np" does not exist` | numpy float passed to psycopg2 | already fixed (start/end cast to `float`) |
| `Modality 'audio' not supported` | sentence-transformers v5 vs KeyBERT | pinned `sentence-transformers==4.1.0` |
| `_parse_error` in `llm` | LLM JSON truncated / fenced | raised tokens to 400 + robust parser; `export_results.py` also recovers it |
| `Video not found` | wrong path | irrelevant now — auto-discovery globs `/kaggle/input/**/*.mp4` |
| `CUDA out of memory` | model too big | keep `FAST_MODE=true`, or lower `MAX_FRAMES` |
| Duplicate rows in DB | random ids on re-run | fixed — `video_id = uuid5(path)` upserts |

## Housekeeping

- **Clear everything for a fresh run:** `TRUNCATE segments, videos RESTART IDENTITY CASCADE;` (Neon SQL editor) + delete `results/*.json`.
- **GPU quota:** 30 GPU-hrs/week. FAST_MODE ≈ 4 min/video → ~150 videos/week. Stop idle sessions.
- **Secrets:** never commit `db_url.txt` / `.env` (both gitignored). Rotate the Neon password if it leaks.
