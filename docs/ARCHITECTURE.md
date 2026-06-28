# Architecture

## Goal

One pipeline that takes an educational video and emits, per meaningful segment, a
clean record: `topic, subject, grade_level, difficulty, content_type, tags,
subtopics, summary, confidence` + a vector embedding. It must run on a **single
free Kaggle T4 (16 GB)**, survive a session dying mid-batch, and work whether the
video is **narrated or silent**, in **any language**.

## The two paths: VOICE vs SILENT

Most failures in the old POC came from treating every video as if it had useful
narration. A silent 3-D molecule animation (-99 dB) produced an empty transcript
and therefore garbage tags. So the first real decision in the pipeline is a route:

```
detect_speech (ffmpeg RMS, dB) ─┐
transcribe (Whisper) → speech_sec┴─► router.decide()
        no speech OR speech_sec < MIN_SPEECH_SEC  → SILENT path
        otherwise                                  → VOICE path
```

* **VOICE path** — the **transcript is ground truth**. Frames are sampled lightly
  (they're hints). The LLM prompt is told to trust the spoken words and treat
  on-screen text/objects as weak supporting evidence.
* **SILENT path** — there are no spoken words, so the **frames carry all meaning**.
  We sample *more* frames, force **OCR on every frame** and **BLIP-2 captions**,
  and the LLM prompt is visual-primary and instructed to return **lower
  confidence**. (See `router.py`, `tagging.py:_voice_prompt/_silent_prompt`.)

Why detect speech by RMS first and *also* transcribe? Because a near-silent clip
can still have a few stray dB. We transcribe early, get the **exact** spoken
seconds, and route on that — `detect_speech` is just the cheap pre-gate. Validated
on real clips: silent ≈ -99 dB; narrated ≈ -16…-30 dB; clean separation.

## One model in VRAM at a time

A T4 cannot hold Whisper + CLIP + YOLO + BLIP-2 + Qwen-7B at once. Every heavy
model is loaded inside `utils.managed_model()`, a context manager that **loads →
yields → deletes the model → empties the CUDA cache**, even if the stage raises.
It logs VRAM before and after so you can *see* memory return to baseline between
stages. The batch loads only the two cheap, shared models (the MiniLM embedder and
spaCy) once and reuses them across all videos; everything GPU-heavy is per-stage.

This is the single most important property for staying inside the free tier.

## Speed: why it's ~2–3 min/video instead of ~7

The old loop ran YOLO + CLIP + OCR on ~30 fixed-rate frames, one frame at a time,
on every video. The wins, all in `ingest.py` + `visual.py`:

1. **Adaptive frame sampling.** Instead of a fixed FPS, take a few uniform anchor
   frames (≈1 every 30 s, min 4) as a backbone and add ffmpeg scene-cut frames as
   a bonus. Smooth animations have few hard cuts, so this collapses 30 frames to
   4–12 on real clips with no loss of coverage.
2. **Gated YOLO.** YOLO only runs on frames whose CLIP scene is "real-world"
   (lab, person-to-camera, whiteboard…). On animation/diagram/slide scenes it is
   skipped — which both **removes the hallucinated objects** (the pendulum cartoon
   that "contained" an apple, a TV and a sports ball) **and** saves time.
3. **Gated OCR.** OCR runs only on text-heavy scenes (slides, notes, diagrams) —
   except on the SILENT path, where text may be the only signal, so OCR runs on
   all frames.
4. **Batched CLIP.** Scene classification is one batched pass over all frames, not
   a Python loop.
5. **Fewer, larger segments → fewer LLM calls.** Segmentation is capped
   (`MAX_SEGMENTS`) with a sane minimum length, and the per-segment Qwen call is
   the most expensive step, so this directly bounds runtime.
6. **Profiles.** `fast` (default, free T4) uses Whisper-medium, YOLOv8n, beam 1.
   `balanced`/`quality` flip every knob together when you have more time/GPU.

## Segmentation

* **Voiced:** embed overlapping transcript windows, find boundaries where adjacent
  windows drop in cosine similarity (knee detection with a fixed-threshold
  fallback), then **merge by duration** so no segment is shorter than
  `MIN_SEGMENT_SEC`. (The old bug merged on start-time distance and collapsed
  everything into ~2 coarse blocks.)
* **Silent:** group consecutive frames by visual scene change into time blocks.

A **consistency pass** then takes a majority vote of subject/grade across a
video's segments and corrects lone outliers (the "Chemistry video, one segment
labelled Mathematics" drift), while keeping the raw label in `subject_raw`.

## Storage is the source of truth

Kaggle can't write to your laptop and its sessions die. So every video is upserted
into **Postgres** keyed by `video_id = uuid5(source_path)` — re-processing a video
**replaces** its row and segments instead of duplicating them. Embeddings go to a
`pgvector` column (semantic search); transcript+OCR go to a generated `tsvector`
column (keyword search). The notebook also drops a human-readable
`results/<name>.json`; your laptop's `sync_results.py` rebuilds that **same** JSON
from the DB so the folder fills in even while Kaggle is still running.

## Restartability

The expensive transcript is checkpointed per video, and the batch skips any
`video_id` already in Postgres (unless you set `SKIP_EXISTING=False`). A killed
12-hour session resumes roughly where it stopped on the next run.

## What this intentionally is **not**

It's a clean, modular **monolith you can run in one notebook**, not a microservice
mesh. Splitting stages into separately deployed services, a queue, autoscaling,
etc. is real work but belongs to a later phase — not the free-Kaggle POC.
