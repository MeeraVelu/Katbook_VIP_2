# Operations

## A. Process videos on Kaggle

1. **Notebook + GPU.** New Notebook → Settings → Accelerator → **GPU T4 x2**.
   (The pipeline uses one GPU; T4 x2 just gives headroom.)
2. **Secrets** (Add-ons → Secrets):
   * `DATABASE_URL` — your Neon/Supabase Postgres URL. *Required to store.*
     Without it the run still works but only writes the `results/` JSON.
   * `HF_TOKEN` — optional. The models used here (Whisper, CLIP, YOLO, BLIP-2,
     Qwen2.5) are **not gated**, so you usually don't need it.
3. **Add your videos.** Put a folder of `.mp4` into a Kaggle **Dataset** and
   attach it with **+ Add Input**. They appear under `/kaggle/input/...` and are
   auto-discovered (no path editing).
4. **Point at your package.** In Cell 0 set `REPO_URL` to your GitHub repo
   (public = no auth needed). If git is blocked, attach the package as a Dataset
   instead — Cell 2 falls back to it automatically.
5. **Edit `CONFIG`** (Cell 0): pick `PROFILE` (`fast` for free T4) and `PROCESS`
   (`"all"`, `"first"`, a number from the printed list, or a filename substring).
6. **Run All.** Watch the per-stage log: each stage prints its time and the VRAM
   before/after, so you can confirm memory returns to baseline between models.

Re-running is safe: finished videos (already in Postgres) are skipped. To force a
redo after changing a prompt/model, set `CONFIG["SKIP_EXISTING"] = False`.

## B. Pull results to your laptop (VS Code)

```bash
# from D:\Katbook_VIP_2
pip install -r requirements-local.txt

# give the scripts the DB URL (either one):
set DATABASE_URL=postgresql://user:pass@host/db      # Windows cmd
$env:DATABASE_URL="postgresql://..."                 # PowerShell
#   ...or write the URL on one line in  db_url.txt  next to the scripts.

python sync_results.py            # one-shot: writes results/<name>.json
python sync_results.py --watch    # keeps mirroring every 30s while Kaggle runs
```

`results/<name>.json` is the same shape the notebook writes, so you get one file
per video plus `all_results.json`. The `results/` folder is git-ignored — it's a
cache; Postgres is the source of truth.

## C. Search what you've processed

```bash
python search.py "time period of a pendulum"
python search.py "rational numbers" --subject Mathematics --k 5
python search.py "atom bonding" --silent     # only silent-video segments
python search.py "oscillation"   --mode fts  # keyword-only (no ML deps needed)
```

Semantic search is automatic when `sentence-transformers` is installed (CPU is
fine); otherwise it falls back to Postgres full-text search.

## D. Tuning

* **Too slow / OOM** → keep `PROFILE="fast"`. It already uses the smallest viable
  models and the fewest frames.
* **Silent video, non-English on-screen text** → add scripts to `OCR_LANGS`, e.g.
  `["en","ta"]`. If Tamil OCR weights fail to load, it falls back to English and
  keeps going (the spoken transcript path is unaffected — Whisper is multilingual
  regardless).
* **Segments too coarse/fine** → adjust `MIN_SEGMENT_SEC` and `MAX_SEGMENTS` in
  `config.py`.
* **Voice/silent misclassified** → adjust `SILENCE_DB` (default -50) and
  `MIN_SPEECH_SEC` (default 3).

## E. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `import torch` fails after install | numpy got bumped. The installer restores the base numpy automatically; if you edited it, re-run Cell 1. |
| No results stored, only JSON | `DATABASE_URL` secret missing or wrong. Check Cell 3 output. |
| Qwen OOM | Ensure only the `fast` profile, GPU T4 selected, and you didn't disable the 4-bit load. Each model frees before the next via `managed_model`. |
| Hallucinated objects in tags | Should be gone (YOLO gated to real-world scenes). If you widened `REALWORLD_SCENES`, you re-enabled it. |
| Tamil OCR error in logs | Expected fallback to English; not fatal. |
| Session died mid-batch | Just re-run; finished videos are skipped, transcripts are checkpointed. |
