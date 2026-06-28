# %% [markdown]
# # Katbook Video Intelligence Platform — POC
# **Full 6-stage pipeline on Kaggle T4 x2 → free cloud Postgres (pgvector)**
#
# This notebook ingests **one** video and runs every stage from the architecture doc:
# ingest/demux → audio (Whisper + diarization + features) → visual (CLIP + YOLO + OCR + BLIP-2)
# → NLP (spaCy + KeyBERT + embeddings + BERTopic) → temporal segmentation →
# LLM semantic fusion (Qwen 4-bit) → storage in Postgres + Qdrant.
#
# **Before running, do these once (see README):**
# 1. Settings → Accelerator → **GPU T4 x2**
# 2. Settings → Internet → **On**
# 3. Add Secrets: `DATABASE_URL` (your Neon/Supabase Postgres URL) and `HF_TOKEN` (HuggingFace token)
# 4. Add Data → upload your sample video as a Dataset, then set `VIDEO_PATH` below.
#
# Models are loaded then **freed** between stages so we never exceed a single T4's 16 GB.

# %% [markdown]
# ## Cell 0 — Configuration (edit this)

# %%
CONFIG = {
    # ---- INPUT: point this at your uploaded video ----
    "VIDEO_PATH": "/kaggle/input/REPLACE-WITH-YOUR-DATASET/sample.mp4",

    # ---- SPEED: True ≈ 3-4 min/video (saves GPU quota, small quality trade-off);
    #            False = full quality ≈ 8-10 min/video. Applied just below. ----
    "FAST_MODE": True,

    # ---- WHICH videos the batch cell processes (Cell 0 prints a numbered list to pick from):
    #   "all"                  -> every discovered video (full batch)
    #   "first"                -> only the first discovered video
    #   3                      -> ONLY video #3 from the printed list (bulletproof; use this
    #                             when a keyword would match more than one file)
    #   "exact_file_name.mp4"  -> only the video whose filename exactly equals this
    #   "<text>"               -> every video whose filename CONTAINS this text (may be >1)
    "PROCESS": "all",

    # Skip videos already processed (already in the DB) so a re-run never redoes them.
    # Set False to FORCE reprocessing (e.g. after improving the prompt / changing models).
    "SKIP_EXISTING": True,

    # ---- OCR languages (EasyOCR). Default English only — it's the most reliable.
    #      You CAN try an Indic script, e.g. ["en","ta"] or ["en","hi"], but some easyocr
    #      versions fail to load Tamil (state_dict size mismatch); the pipeline then falls
    #      back to English automatically. On-screen text is a minor signal — the Tamil
    #      TRANSCRIPT (Whisper) is what drives the tags, so English-only OCR is fine. ----
    "OCR_LANGS": ["en"],

    # ---- Stage toggles (turn off heavy parts if you hit OOM / time limits) ----
    "ENABLE_DIARIZATION": True,   # pyannote 3.1 — needs HF_TOKEN + accepted model terms
    "ENABLE_BLIP2":        True,  # frame captioning — heaviest visual model (~8GB)
    "ENABLE_BERTOPIC":     True,  # topic modelling — needs enough windows
    "ENABLE_QDRANT":       True,  # local vector DB demo (in addition to pgvector)

    # ---- Frame sampling (Stage 1) ----
    "FPS_SAMPLE": 0.5,            # frames per second to extract (0.5 = 1 frame / 2s)
    "MAX_FRAMES": 60,             # hard cap to keep T4 fast

    # ---- Models ----
    "WHISPER_MODEL": "large-v3",            # use "medium" if low on time/VRAM
    "LLM_MODEL": "Qwen/Qwen2.5-7B-Instruct",# stands in for Qwen3-32B (won't fit T4)
    "EMBED_MODEL": "sentence-transformers/all-MiniLM-L6-v2",
    "CLIP_MODEL": "openai/clip-vit-large-patch14",
    "BLIP2_MODEL": "Salesforce/blip2-opt-2.7b",
    "YOLO_MODEL": "yolov8m.pt",
    "LLM_MAX_NEW_TOKENS": 400,   # per-segment LLM output budget (Cell 11)

    # ---- Segmentation (Stage 5) ----
    "WINDOW_SEC": 30,             # transcript window size for embeddings
    "MIN_SEGMENT_SEC": 90,        # minimum segment duration guard
    "SIM_DROP_FALLBACK": 0.25,    # cosine-drop threshold if kneed finds nothing
}

# CLIP candidate scene labels — tune to your content taxonomy
SCENE_LABELS = [
    "teacher at a whiteboard", "slide presentation", "laboratory experiment",
    "student discussion", "diagram explanation", "demonstration with equipment",
    "animated visualization", "text-heavy slide", "person talking to camera",
    "handwritten notes",
]
# Auto-discover every .mp4 in any attached dataset, so a filename typo can never
# fail a committed "Save & Run All". VIDEO_PATHS feeds the batch loop; VIDEO_PATH
# (first video) feeds the single-video cells. Falls back to the manual path above.
import glob as _glob
VIDEO_PATHS = sorted(_glob.glob("/kaggle/input/**/*.mp4", recursive=True))
if VIDEO_PATHS:
    CONFIG["VIDEO_PATH"] = VIDEO_PATHS[0]
print(f"Discovered {len(VIDEO_PATHS)} video(s)  (set CONFIG['PROCESS'] to a number to pick one):")
for _i, _v in enumerate(VIDEO_PATHS, start=1):
    print(f"   {_i}. {_v.split('/')[-1]}")

# Apply FAST_MODE: one switch flips every speed knob (≈3-4 min/video, ~1/3 the GPU quota).
if CONFIG.get("FAST_MODE"):
    CONFIG.update({
        "WHISPER_MODEL": "medium",                     # large-v3 -> medium (~2x faster ASR)
        "CLIP_MODEL": "openai/clip-vit-base-patch32",  # large-patch14 -> base (~3x faster)
        "YOLO_MODEL": "yolov8n.pt",                    # medium -> nano (~3x faster)
        "MAX_FRAMES": 30,                              # half the frames
        "FPS_SAMPLE": 0.25,                            # 1 frame / 4s
        "ENABLE_BLIP2": False,                         # skip heaviest visual model
        "ENABLE_DIARIZATION": False,                   # skip speaker turns
        "LLM_MAX_NEW_TOKENS": 400,                     # enough to finish the JSON (250 truncated it)
    })
    print("FAST_MODE ON  -> medium Whisper, base CLIP, nano YOLO, 30 frames, no BLIP-2/diarization.")
else:
    print("FAST_MODE OFF -> full quality (large-v3 / CLIP-large / YOLOv8m / BLIP-2).")

print("Config loaded. VIDEO_PATH =", CONFIG["VIDEO_PATH"])

# %% [markdown]
# ## Cell 1 — Install dependencies
# Kaggle ships torch/transformers; we add the pipeline-specific libs. (~3-5 min first run.)

# %%
# Smart installer: only install a package if it's MISSING or the version doesn't match a
# pin. Saves time + disk on re-runs (skips work already done) instead of reinstalling every
# time. (Kaggle wipes the env on a fresh session, so first run still installs everything.)
import subprocess, sys, re as _re
import importlib.metadata as _md
from importlib.metadata import version as _ver, PackageNotFoundError

# Capture the BASE numpy version BEFORE any install. Kaggle's torch is built for exactly
# this numpy; if a dependency changes it, `import torch` breaks. We restore this exact
# version after installing, so torch imports cleanly in Cell 2 with NO kernel restart.
try:
    _BASE_NUMPY = _ver("numpy")
except Exception:
    _BASE_NUMPY = None

def _check(spec):
    """Return ('ok'|'install'|'update', name, spec/version) WITHOUT installing."""
    name = _re.split(r"[<>=!]", spec, 1)[0].strip()
    want = spec.split("==", 1)[1] if "==" in spec else None
    try:
        have = _ver(name)
        if want is None or have == want:
            return ("ok", name, have)            # already satisfied -> skip
        return ("update", name, spec)
    except PackageNotFoundError:
        return ("install", name, spec)

PKGS = [
    "faster-whisper==1.0.3", "pyannote.audio==3.3.2",
    "langdetect", "librosa", "kneed",
    "ultralytics",                     # UNPINNED: 8.3.0 forced numpy<2 and broke torch; latest supports numpy 2.x
    "easyocr==1.7.2",
    "keybert", "sentence-transformers==4.1.0", "bertopic",   # st pin: v5 breaks KeyBERT
    "qdrant-client", "psycopg2-binary", "sqlalchemy>=2.0", "pgvector",
    "bitsandbytes>=0.43", "accelerate>=0.30", "ffmpeg-python",
    # NOTE: gradio is installed lazily in Cell 14 (search UI) ONLY.
]
# Check everything first, then install ONLY the missing/outdated ones in a SINGLE pip call
# (one dependency resolution instead of ~18 separate pip runs — much faster on a fresh session).
_installed = [_check(p) for p in PKGS]
_to_install = [r[2] for r in _installed if r[0] != "ok"]
if _to_install:
    print(f"Installing {len(_to_install)} missing/outdated package(s) in one pip call; "
          f"{len(PKGS) - len(_to_install)} already present (skipped)...")
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", *_to_install], check=False)
else:
    print("All dependencies already present — skipping install entirely.")

# Restore numpy to the EXACT base version if anything changed it (keeps torch importable
# in-place, no restart). numpy isn't imported in-kernel before this, so the restore is clean.
_did = [r for r in _installed if r[0] != "ok"]
_npv = _md.version("numpy")
if _BASE_NUMPY and _npv != _BASE_NUMPY:
    print(f"numpy changed {_BASE_NUMPY} -> {_npv}; restoring base {_BASE_NUMPY} for torch.")
    subprocess.run([sys.executable, "-m", "pip", "install", "-q",
                    f"numpy=={_BASE_NUMPY}", "--no-deps"], check=False)
    _did += [("restore", "numpy", _BASE_NUMPY)]
_skipped = [r for r in _installed if r[0] == "ok"]
print(f"Skipped {len(_skipped)} already-present packages; installed/updated {len(_did)}:")
for st, n, v in _did:
    print(f"   {st}: {n} {v}")

# spaCy English model — only download if not already loadable
try:
    import spacy; spacy.load("en_core_web_sm"); print("spaCy en_core_web_sm: present")
except Exception:
    subprocess.run([sys.executable, "-m", "spacy", "download", "en_core_web_sm"], check=False)
    print("spaCy en_core_web_sm: downloaded")

print(f"Dependencies ready. numpy=={_md.version('numpy')} (base, torch-compatible). "
      "No restart needed — run straight on.")

# %% [markdown]
# ## Cell 2 — Imports, GPU check, helpers

# %%
import os, gc, json, math, re, time
from pathlib import Path
import numpy as np
import torch

print("CUDA available:", torch.cuda.is_available())
print("GPU count:", torch.cuda.device_count())
for i in range(torch.cuda.device_count()):
    print(f"  cuda:{i} =", torch.cuda.get_device_name(i))

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
WORK = Path("/kaggle/working")
FRAMES_DIR = WORK / "frames"; FRAMES_DIR.mkdir(exist_ok=True, parents=True)
AUDIO_PATH = WORK / "audio.wav"

def free_vram(*objs):
    """Delete models and clear CUDA cache between stages."""
    for o in objs:
        try: del o
        except Exception: pass
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.ipc_collect()

def vram_report():
    if torch.cuda.is_available():
        a = torch.cuda.memory_allocated()/1e9
        print(f"   VRAM allocated: {a:.1f} GB")

def load_whisper():
    """Load faster-whisper with an adaptive compute type.
    float16 is fastest on T4 but some Kaggle/CTranslate2 builds reject it when the
    CUDA backend can't init (it falls back to CPU, which has no efficient float16).
    Try float16 → int8_float16 (GPU) / int8 (CPU) → CPU int8, so the stage never dies."""
    from faster_whisper import WhisperModel
    attempts = [(DEVICE, "float16"),
                (DEVICE, "int8_float16" if DEVICE == "cuda" else "int8"),
                ("cpu", "int8")]
    last = None
    seen = set()
    for dev, ct in attempts:
        if (dev, ct) in seen:
            continue
        seen.add((dev, ct))
        try:
            m = WhisperModel(CONFIG["WHISPER_MODEL"], device=dev, compute_type=ct)
            print(f"   whisper: device={dev} compute_type={ct}")
            return m
        except Exception as e:
            last = e
            print(f"   whisper: {dev}/{ct} unavailable ({e}); trying next…")
    raise last

# The single growing payload that flows through every stage (the doc's JobPayload)
PAYLOAD = {
    "video_id": None, "source_path": CONFIG["VIDEO_PATH"],
    "transcript": [], "speakers": [], "language": None,
    "audio_features": {}, "frame_analyses": [], "nlp": {},
    "segments": [], "status": "processing", "stage_timings": {},
}

import uuid
# Stable, deterministic id derived from the file path: re-processing the SAME video
# overwrites its old rows (Cell 12's DELETE) instead of creating duplicate copies.
PAYLOAD["video_id"] = str(uuid.uuid5(uuid.NAMESPACE_URL, CONFIG["VIDEO_PATH"]))
print("video_id:", PAYLOAD["video_id"], "(stable for", CONFIG["VIDEO_PATH"], ")")

# %% [markdown]
# ## Cell 3 — Secrets (DATABASE_URL + HF_TOKEN)

# %%
from kaggle_secrets import UserSecretsClient
sec = UserSecretsClient()
try:
    DATABASE_URL = sec.get_secret("DATABASE_URL")
    # SQLAlchemy + psycopg2 wants 'postgresql+psycopg2://'
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg2://", 1)
    elif DATABASE_URL.startswith("postgresql://"):
        DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://", 1)
    print("DATABASE_URL loaded.")
except Exception as e:
    DATABASE_URL = None
    print("WARNING: no DATABASE_URL secret. Storage cell will be skipped.", e)

try:
    HF_TOKEN = sec.get_secret("HF_TOKEN")
    os.environ["HF_TOKEN"] = HF_TOKEN
    os.environ["HUGGING_FACE_HUB_TOKEN"] = HF_TOKEN
    print("HF_TOKEN loaded.")
except Exception as e:
    HF_TOKEN = None
    print("WARNING: no HF_TOKEN. Diarization will be skipped.", e)

# %% [markdown]
# ## Cell 3b — BATCH: process EVERY discovered video in ONE run
# This is the **all-in-one** path. It loops over `VIDEO_PATHS` (auto-discovered in Cell 0),
# runs the full pipeline per video, stores each to Postgres (stable `video_id` → no dupes),
# and writes `results_<id>.json`. Models load→use→free per stage, so VRAM never accumulates
# across videos. The small embedder loads once for the whole batch.
#
# **HOW TO RUN (batch):** Cells 0,1,2,3 → THIS cell. (Skip the single-video Cells 4–13b.)
# Then Cell 14 for the search UI. Set `RUN_BATCH=False` to use the single-video cells instead.

# %%
RUN_BATCH = True

if RUN_BATCH:
    import ffmpeg, uuid as _uuid, platform
    from datetime import datetime, timezone
    from collections import Counter
    from PIL import Image

    # Self-bootstrap the DB secret so this cell runs even if Cell 3 wasn't run this session.
    try:
        DATABASE_URL
    except NameError:
        from kaggle_secrets import UserSecretsClient
        try:
            DATABASE_URL = UserSecretsClient().get_secret("DATABASE_URL")
            if DATABASE_URL.startswith("postgres://"):
                DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg2://", 1)
            elif DATABASE_URL.startswith("postgresql://"):
                DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://", 1)
            print("DATABASE_URL loaded (bootstrapped in batch cell).")
        except Exception as _e:
            DATABASE_URL = None
            print("WARNING: no DATABASE_URL — results saved to JSON only, not Postgres.", _e)

    # Embedder loads ONCE for the whole batch (it's small; heavy models load per stage).
    from sentence_transformers import SentenceTransformer
    _embedder = SentenceTransformer(CONFIG["EMBED_MODEL"], device=DEVICE)

    def _build_windows(transcript, win=CONFIG["WINDOW_SEC"]):
        if not transcript: return []
        end_t = transcript[-1]["end"]; out=[]; t=0.0
        while t < end_t:
            chunk = " ".join(s["text"] for s in transcript if t <= s["start"] < t+win)
            out.append({"start": t, "end": min(t+win, end_t), "text": chunk}); t += win
        return [w for w in out if w["text"].strip()]

    def _segment(windows, win_emb, duration):
        from kneed import KneeLocator
        if len(windows) <= 1:
            return [{"start": 0.0, "end": duration or (windows[-1]["end"] if windows else 0)}]
        sims = [float(np.dot(win_emb[i], win_emb[i+1])) for i in range(len(win_emb)-1)]
        drops = [1-s for s in sims]; thresh = CONFIG["SIM_DROP_FALLBACK"]
        try:
            sd = sorted(drops)
            kn = KneeLocator(range(len(sd)), sd, curve="convex", direction="increasing")
            if kn.knee is not None: thresh = max(sd[kn.knee], 0.15)
        except Exception: pass
        bounds = sorted(set([0] + [i+1 for i, d in enumerate(drops) if d >= thresh] + [len(windows)]))
        segs = [{"start": windows[a]["start"], "end": windows[b-1]["end"]}
                for a, b in zip(bounds[:-1], bounds[1:])]
        merged = []
        for s in segs:
            if merged and (s["start"] - merged[-1]["start"]) < CONFIG["MIN_SEGMENT_SEC"]:
                merged[-1]["end"] = s["end"]
            else: merged.append(s)
        return merged

    def process_video(video_path):
        """Run the full pipeline on ONE video. Returns (payload, seg_emb)."""
        t_all = time.time()
        P = {"video_id": str(_uuid.uuid5(_uuid.NAMESPACE_URL, video_path)),
             "source_path": video_path, "transcript": [], "language": None,
             "audio_features": {}, "frame_analyses": [], "nlp": {}, "segments": [],
             "stage_timings": {}, "status": "processing"}
        frames_dir = WORK / "frames"; frames_dir.mkdir(exist_ok=True, parents=True)
        for f in frames_dir.glob("frame_*.jpg"): f.unlink()   # clear previous video's frames
        audio_path = WORK / "audio.wav"

        # --- Stage 1: ingest (ffmpeg) ---
        t0 = time.time()
        (ffmpeg.input(video_path).output(str(audio_path), ac=1, ar=16000, format="wav",
            loglevel="error").overwrite_output().run())
        (ffmpeg.input(video_path).filter("fps", fps=CONFIG["FPS_SAMPLE"])
            .output(str(frames_dir / "frame_%04d.jpg"), loglevel="error").overwrite_output().run())
        frame_files = sorted(frames_dir.glob("frame_*.jpg"))[:CONFIG["MAX_FRAMES"]]
        P["duration"] = float(ffmpeg.probe(video_path)["format"]["duration"])
        frame_times = [i / CONFIG["FPS_SAMPLE"] for i in range(len(frame_files))]
        P["stage_timings"]["ingest"] = time.time() - t0

        # --- Stage 2A: transcription (faster-whisper) ---
        t0 = time.time()
        whisper = load_whisper()
        seg_iter, info = whisper.transcribe(str(audio_path), word_timestamps=True, vad_filter=True)
        P["transcript"] = [{"start": round(s.start, 2), "end": round(s.end, 2),
                            "text": s.text.strip()} for s in seg_iter]
        P["language"] = info.language
        full_text = " ".join(s["text"] for s in P["transcript"])
        free_vram(whisper); P["stage_timings"]["whisper"] = time.time() - t0

        # --- Stage 2A: audio features (librosa) ---
        import librosa
        y, sr = librosa.load(str(audio_path), sr=16000)
        intervals = librosa.effects.split(y, top_db=30)
        voiced = sum((e-s) for s, e in intervals)/sr if len(intervals) else 0
        P["audio_features"] = {"rms_energy": round(float(np.mean(librosa.feature.rms(y=y))), 4),
            "silence_ratio": round(1 - voiced/max(P["duration"], 1e-6), 3),
            "words_per_minute": round(len(full_text.split())/max(P["duration"]/60, 1e-6), 1)}
        free_vram(y)

        # --- Stage 2B: visual (CLIP + YOLO + OCR [+ BLIP-2]) ---
        t0 = time.time()
        FA = [{"index": i, "time": round(frame_times[i], 1), "path": str(p),
               "scene": None, "objects": [], "ocr": "", "caption": ""}
              for i, p in enumerate(frame_files)]
        from transformers import CLIPProcessor, CLIPModel
        clip = CLIPModel.from_pretrained(CONFIG["CLIP_MODEL"]).to(DEVICE).eval()
        clip_proc = CLIPProcessor.from_pretrained(CONFIG["CLIP_MODEL"])
        with torch.no_grad():
            for fa in FA:
                inp = clip_proc(text=SCENE_LABELS, images=Image.open(fa["path"]).convert("RGB"),
                                return_tensors="pt", padding=True).to(DEVICE)
                logits = clip(**inp).logits_per_image.softmax(dim=1)[0]
                fa["scene"] = SCENE_LABELS[int(logits.argmax())]
        free_vram(clip, clip_proc)
        from ultralytics import YOLO
        yolo = YOLO(CONFIG["YOLO_MODEL"])
        for fa in FA:
            res = yolo(fa["path"], verbose=False, device=0 if DEVICE == "cuda" else "cpu")[0]
            fa["objects"] = sorted(set(res.names[int(c)] for c in res.boxes.cls.tolist())) if res.boxes is not None else []
        free_vram(yolo)
        import easyocr
        _ocr_langs = CONFIG.get("OCR_LANGS", ["en"])
        try:
            reader = easyocr.Reader(_ocr_langs, gpu=(DEVICE == "cuda"))
        except Exception as _ocr_e:
            print(f"   OCR langs {_ocr_langs} failed to load ({str(_ocr_e)[:70]}); using ['en'] only.")
            reader = easyocr.Reader(["en"], gpu=(DEVICE == "cuda"))
        for fa in FA:
            try: fa["ocr"] = " ".join(reader.readtext(fa["path"], detail=0, paragraph=True))[:500]
            except Exception: fa["ocr"] = ""
        free_vram(reader)
        if CONFIG["ENABLE_BLIP2"]:
            from transformers import Blip2Processor, Blip2ForConditionalGeneration
            bp = Blip2Processor.from_pretrained(CONFIG["BLIP2_MODEL"])
            bl = Blip2ForConditionalGeneration.from_pretrained(CONFIG["BLIP2_MODEL"],
                torch_dtype=torch.float16).to(DEVICE).eval()
            step = max(1, len(FA)//12)
            with torch.no_grad():
                for fa in FA[::step]:
                    inp = bp(images=Image.open(fa["path"]).convert("RGB"),
                             return_tensors="pt").to(DEVICE, torch.float16)
                    fa["caption"] = bp.batch_decode(bl.generate(**inp, max_new_tokens=40),
                                                    skip_special_tokens=True)[0].strip()
            free_vram(bl, bp)
        P["frame_analyses"] = FA
        P["stage_timings"]["visual"] = time.time() - t0

        # --- Stage 3: NLP (spaCy + keywords + embeddings) ---
        t0 = time.time()
        import spacy
        nlp = spacy.load("en_core_web_sm"); doc = nlp(full_text[:100000])
        entities = sorted(set((e.text, e.label_) for e in doc.ents))[:40]
        keywords = []
        if full_text.strip():
            try:
                from keybert import KeyBERT
                keywords = KeyBERT(model=_embedder).extract_keywords(full_text,
                    keyphrase_ngram_range=(1, 2), stop_words="english", top_n=20)
            except Exception:
                cnt = Counter(c.text.lower().strip() for c in doc.noun_chunks
                              if 2 <= len(c.text.strip()) <= 40)
                n = sum(cnt.values()) or 1
                keywords = [(t, round(c/n, 3)) for t, c in cnt.most_common(20)]
        P["nlp"] = {"entities": [{"text": t, "label": l} for t, l in entities],
                    "keywords": [{"term": k, "score": round(s, 3)} for k, s in keywords]}
        free_vram(nlp)
        windows = _build_windows(P["transcript"])
        win_emb = _embedder.encode([w["text"] for w in windows], normalize_embeddings=True) \
                  if windows else np.zeros((0, 384))
        P["stage_timings"]["nlp"] = time.time() - t0

        # --- Stage 5: segmentation + attach signals ---
        t0 = time.time()
        segs = _segment(windows, win_emb, P["duration"])
        for s in segs:
            s["text"] = " ".join(t["text"] for t in P["transcript"] if s["start"] <= t["start"] < s["end"])
            sf = [f for f in FA if s["start"] <= f["time"] < s["end"]]
            s["scenes"] = sorted(set(f["scene"] for f in sf if f["scene"]))
            s["objects"] = sorted(set(o for f in sf for o in f["objects"]))
            s["ocr"] = " ".join(f["ocr"] for f in sf if f["ocr"])[:600]
            s["captions"] = [f["caption"] for f in sf if f["caption"]][:3]
        P["segments"] = segs
        P["stage_timings"]["segmentation"] = time.time() - t0

        # --- Stage 4: LLM fusion (Qwen 4-bit) ---
        t0 = time.time()
        from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig
        bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_compute_dtype=torch.float16,
            bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True)
        tok = AutoTokenizer.from_pretrained(CONFIG["LLM_MODEL"])
        llm = AutoModelForCausalLM.from_pretrained(CONFIG["LLM_MODEL"], quantization_config=bnb,
            device_map="auto", torch_dtype=torch.float16)
        SCHEMA = ('Return ONLY valid JSON: {"topic": str, "subtopics": [str], '
            '"content_type": "lecture|tutorial|demo|discussion|animation", '
            '"difficulty": "beginner|intermediate|advanced|expert", "grade_level": str, '
            '"subject": str, "summary": str, "tags": [str], '
            '"speaker_role": "teacher|student|narrator|unknown", "language": str, '
            '"has_visual_content": bool, "confidence": float}')
        DOMAIN = ("Katbook is a multilingual K-12 EdTech platform; content is often in Tamil or "
            "English. Decide topic/subject/grade ONLY from the spoken TRANSCRIPT — that is the "
            "ground truth of what is being taught. Detected objects and scenes come from automatic "
            "image tagging of (often animated) visuals; they are NOISY and frequently misleading, "
            "so treat them as weak hints ONLY and never as the subject. Use a BROAD school taxonomy: "
            "Languages (Tamil, English, Alphabets & Phonics, Vocabulary), Mathematics, "
            "Science (Physics/Chemistry/Biology), Environmental Studies, Social Studies, "
            "General Knowledge, Rhymes. Pick the grade that fits (an alphabet/rhyme/animation video "
            "for young kids is Kindergarten or Grade 1-2). Write topic, subject, summary, subtopics "
            "and tags in ENGLISH (never raw transcript fragments). 'language' = the spoken language.")
        for i, s in enumerate(P["segments"]):
            prompt = (f"{DOMAIN}\n\n"
                f"Detected spoken language: {P.get('language')}\n\n"
                f"TRANSCRIPT (base your tags on THIS — the actual taught content):\n"
                f"\"\"\"{s['text'][:3000]}\"\"\"\n\n"
                f"On-screen text (OCR, may help confirm the topic): {s['ocr'][:300]}\n"
                f"Weak visual hints (auto-detected, often wrong — do NOT make these the subject): "
                f"scenes={s['scenes']}, objects={s['objects']}\n\n{SCHEMA}")
            text = tok.apply_chat_template(
                [{"role": "system", "content": "You are a precise educational video tagging engine."},
                 {"role": "user", "content": prompt}], tokenize=False, add_generation_prompt=True)
            inp = tok(text, return_tensors="pt").to(llm.device)
            with torch.no_grad():
                out = llm.generate(**inp, max_new_tokens=CONFIG.get("LLM_MAX_NEW_TOKENS", 400),
                    do_sample=False, pad_token_id=tok.eos_token_id)
            raw = tok.decode(out[0][inp.input_ids.shape[1]:], skip_special_tokens=True)
            s["llm"] = _parse_llm(raw)
        free_vram(llm, tok); P["stage_timings"]["llm"] = time.time() - t0

        seg_summaries = [(s.get("llm", {}).get("summary") or s["text"][:300]) for s in P["segments"]]
        seg_emb = _embedder.encode(seg_summaries, normalize_embeddings=True) if seg_summaries else np.zeros((0, 384))
        P["status"] = "complete"; P["stage_timings"]["total"] = time.time() - t_all
        return P, seg_emb

    import re as _re_mod
    _re_batch = _re_mod.compile(r"\{.*\}", _re_mod.DOTALL)

    def _parse_llm(raw):
        """Robust LLM JSON parse: strip ```json fences, repair truncation, regex-fallback."""
        t = (raw or "").strip()
        t = _re_mod.sub(r"^```(?:json)?", "", t).strip()
        t = _re_mod.sub(r"```$", "", t).strip()
        m = _re_mod.search(r"\{.*", t, _re_mod.DOTALL)
        if not m:
            return {"_parse_error": raw[:300]}
        js = m.group(0)
        for cand in (js, js + "}", js + '"}', js + '"}}', js[:js.rfind("}") + 1] if "}" in js else js):
            try:
                return json.loads(cand)
            except Exception:
                pass
        def grab(k):
            mm = _re_mod.search(rf'"{k}"\s*:\s*"([^"]*)"', js)
            return mm.group(1) if mm else None
        tg = _re_mod.search(r'"tags"\s*:\s*\[(.*?)\]', js, _re_mod.DOTALL)
        out = {"topic": grab("topic"), "subject": grab("subject"), "grade_level": grab("grade_level"),
               "difficulty": grab("difficulty"), "content_type": grab("content_type"),
               "summary": grab("summary"),
               "tags": [x.strip().strip('"') for x in tg.group(1).split(",") if x.strip()] if tg else []}
        out = {k: v for k, v in out.items() if v}
        return out or {"_parse_error": raw[:300]}

    def store_payload(P, seg_emb, engine):
        from sqlalchemy import text as sqltext
        DIM = int(seg_emb.shape[1]) if seg_emb.shape[0] else 384
        with engine.begin() as cx:
            cx.execute(sqltext("CREATE EXTENSION IF NOT EXISTS vector"))
            cx.execute(sqltext("""CREATE TABLE IF NOT EXISTS videos (
                video_id UUID PRIMARY KEY, source_path TEXT, duration FLOAT, language TEXT,
                audio_features JSONB, nlp JSONB, stage_timings JSONB,
                created_at TIMESTAMPTZ DEFAULT now())"""))
            cx.execute(sqltext(f"""CREATE TABLE IF NOT EXISTS segments (
                id SERIAL PRIMARY KEY, video_id UUID REFERENCES videos(video_id),
                seg_index INT, start_sec FLOAT, end_sec FLOAT, transcript TEXT,
                scenes JSONB, objects JSONB, ocr TEXT, llm JSONB, embedding vector({DIM}),
                fts tsvector GENERATED ALWAYS AS (to_tsvector('english', coalesce(transcript,''))) STORED)"""))
            cx.execute(sqltext("CREATE INDEX IF NOT EXISTS seg_fts_idx ON segments USING GIN(fts)"))
            cx.execute(sqltext("""INSERT INTO videos(video_id,source_path,duration,language,audio_features,nlp,stage_timings)
                VALUES (:vid,:sp,:dur,:lang,:af,:nlp,:st) ON CONFLICT (video_id)
                DO UPDATE SET duration=:dur, language=:lang, audio_features=:af, nlp=:nlp, stage_timings=:st"""),
                {"vid": P["video_id"], "sp": P["source_path"], "dur": float(P["duration"]),
                 "lang": P["language"], "af": json.dumps(P["audio_features"]),
                 "nlp": json.dumps(P["nlp"]), "st": json.dumps(P["stage_timings"])})
            cx.execute(sqltext("DELETE FROM segments WHERE video_id=:v"), {"v": P["video_id"]})
            for i, s in enumerate(P["segments"]):
                emb = seg_emb[i].tolist() if i < len(seg_emb) else [0.0]*DIM
                cx.execute(sqltext("""INSERT INTO segments
                    (video_id,seg_index,start_sec,end_sec,transcript,scenes,objects,ocr,llm,embedding)
                    VALUES (:v,:i,:a,:b,:tr,:sc,:ob,:ocr,:llm,:emb)"""),
                    {"v": P["video_id"], "i": i, "a": float(s["start"]), "b": float(s["end"]),
                     "tr": s["text"], "sc": json.dumps(s["scenes"]), "ob": json.dumps(s["objects"]),
                     "ocr": s["ocr"], "llm": json.dumps(s.get("llm", {})), "emb": str(emb)})

    def write_results_json(P):
        def dom(seg):
            fr = [f for f in P["frame_analyses"] if seg["start"] <= f["time"] < seg["end"] and f.get("scene")]
            return Counter(f["scene"] for f in fr).most_common(1)[0][0] if fr else (seg.get("scenes") or [None])[0]
        res = {"video_id": P["video_id"][:8], "source": P["source_path"],
            "processed_at": datetime.now(timezone.utc).isoformat(),
            "os": f"{platform.system()} {platform.release()}", "python": platform.python_version(),
            "duration_sec": round(float(P["duration"]), 2), "language": P["language"],
            "segment_count": len(P["segments"]),
            "pipeline_time_sec": round(sum(P["stage_timings"].values()), 1),
            "segments": [{"segment": i, "start": round(float(s["start"]), 1), "end": round(float(s["end"]), 1),
                "topic": (s.get("llm") or {}).get("topic"), "difficulty": (s.get("llm") or {}).get("difficulty"),
                "subject": (s.get("llm") or {}).get("subject"), "grade": (s.get("llm") or {}).get("grade_level"),
                "content_type": (s.get("llm") or {}).get("content_type"), "tags": (s.get("llm") or {}).get("tags", []),
                "summary": (s.get("llm") or {}).get("summary"), "confidence": (s.get("llm") or {}).get("confidence"),
                "dominant_scene": dom(s), "objects_detected": s.get("objects", [])}
                for i, s in enumerate(P["segments"], start=1)]}
        path = WORK / f"results_{res['video_id']}.json"
        path.write_text(json.dumps(res, indent=2, default=str))
        return res, path

    # ---- the loop ----
    _engine = None
    if DATABASE_URL:
        from sqlalchemy import create_engine
        _engine = create_engine(DATABASE_URL, pool_pre_ping=True)

    # Pick which videos to process based on CONFIG["PROCESS"] (set in Cell 0).
    # NO silent fallback: if your selection matches nothing, we process NOTHING and tell you,
    # so you never accidentally re-run the wrong (first) video.
    _raw = CONFIG.get("PROCESS", "all")
    if isinstance(_raw, int) or (isinstance(_raw, str) and _raw.strip().isdigit()):
        _k = int(_raw)                                   # pick by 1-based index — never ambiguous
        _to_process = VIDEO_PATHS[_k-1:_k] if 1 <= _k <= len(VIDEO_PATHS) else []
        if not _to_process:
            print(f"⚠ PROCESS={_raw} is out of range (1..{len(VIDEO_PATHS)}). Nothing selected.")
    else:
        _sel = str(_raw).strip().lower()
        if _sel == "all":
            _to_process = VIDEO_PATHS
        elif _sel in ("first", "one", "single"):
            _to_process = VIDEO_PATHS[:1]
        else:
            _exact = [v for v in VIDEO_PATHS if v.split("/")[-1].lower() == _sel]
            _to_process = _exact or [v for v in VIDEO_PATHS if _sel in v.lower()]   # NO fallback
            if not _to_process:
                print(f"⚠ PROCESS={_raw!r} matched NO video. Set PROCESS to one of these numbers:")
                for _i, _v in enumerate(VIDEO_PATHS, 1):
                    print(f"     {_i}. {_v.split('/')[-1]}")
            elif len(_to_process) > 1:
                print(f"⚠ {_raw!r} matched {len(_to_process)} videos — processing all. "
                      f"Use a NUMBER (e.g. PROCESS=2) to pick exactly one.")

    # Skip videos already in the DB (unless SKIP_EXISTING is False).
    _existing = set()
    if _engine and CONFIG.get("SKIP_EXISTING", True):
        try:
            from sqlalchemy import text as _sqltext
            with _engine.connect() as _cx:
                _existing = {str(r[0]) for r in _cx.execute(
                    _sqltext("SELECT DISTINCT video_id FROM videos")).fetchall()}
        except Exception:
            _existing = set()   # tables don't exist yet (first run)

    print(f"\n=== BATCH (PROCESS={CONFIG.get('PROCESS')!r}): {len(_to_process)} selected of "
          f"{len(VIDEO_PATHS)} video(s) ===")
    batch_summary = []
    for n, vpath in enumerate(_to_process, start=1):
        _vid = str(_uuid.uuid5(_uuid.NAMESPACE_URL, vpath))
        if _vid in _existing:
            print(f"\n--- [{n}/{len(_to_process)}] ⏭  SKIP (already processed): {Path(vpath).name}")
            batch_summary.append({"video": Path(vpath).name, "skipped": "already in DB"})
            continue
        print(f"\n--- [{n}/{len(_to_process)}] {vpath}")
        try:
            P, seg_emb = process_video(vpath)
            if _engine: store_payload(P, seg_emb, _engine)
            res, path = write_results_json(P)
            topics = sorted({s["topic"] for s in res["segments"] if s["topic"]})
            batch_summary.append({"video": Path(vpath).name, "segments": len(P["segments"]),
                "minutes": round(P["stage_timings"]["total"]/60, 1), "topics": topics})
            print(f"    ✓ {len(P['segments'])} segments, {P['stage_timings']['total']/60:.1f} min, "
                  f"topics={topics} -> {path.name}")
        except Exception as e:
            print(f"    ✗ FAILED: {e}")
            batch_summary.append({"video": Path(vpath).name, "error": str(e)[:200]})

    print("\n=== BATCH COMPLETE ===")
    for b in batch_summary: print("  ", b)

# %% [markdown]
# ## Cell 4 — Stage 1: Ingest & Demux (ffmpeg)
# *(Single-video path — skip Cells 4–13b if you ran the batch cell above.)*
# Extract 16 kHz mono WAV (Whisper-optimal) + sampled frames. CPU-bound, no GPU.

# %%
import ffmpeg
assert Path(CONFIG["VIDEO_PATH"]).exists(), f"Video not found: {CONFIG['VIDEO_PATH']} — fix VIDEO_PATH in Cell 0"

t0 = time.time()
# 1a. Audio: 16kHz mono PCM
(ffmpeg.input(CONFIG["VIDEO_PATH"])
    .output(str(AUDIO_PATH), ac=1, ar=16000, format="wav", loglevel="error")
    .overwrite_output().run())

# 1b. Frames at FPS_SAMPLE
(ffmpeg.input(CONFIG["VIDEO_PATH"])
    .filter("fps", fps=CONFIG["FPS_SAMPLE"])
    .output(str(FRAMES_DIR / "frame_%04d.jpg"), loglevel="error")
    .overwrite_output().run())

frame_files = sorted(FRAMES_DIR.glob("frame_*.jpg"))[:CONFIG["MAX_FRAMES"]]
# probe duration
probe = ffmpeg.probe(CONFIG["VIDEO_PATH"])
duration = float(probe["format"]["duration"])
PAYLOAD["duration"] = duration
PAYLOAD["stage_timings"]["ingest"] = time.time() - t0
print(f"Duration: {duration:.1f}s | audio: {AUDIO_PATH.exists()} | frames: {len(frame_files)}")
# timestamp for each frame (seconds)
frame_times = [(i / CONFIG["FPS_SAMPLE"]) for i in range(len(frame_files))]

# %% [markdown]
# ## Cell 5 — Stage 2A: Audio — transcription (faster-whisper)

# %%
t0 = time.time()
whisper = load_whisper()
segments_iter, info = whisper.transcribe(str(AUDIO_PATH), word_timestamps=True, vad_filter=True)

transcript = []
for seg in segments_iter:
    transcript.append({"start": round(seg.start, 2), "end": round(seg.end, 2),
                       "text": seg.text.strip()})
PAYLOAD["transcript"] = transcript
PAYLOAD["language"] = info.language
PAYLOAD["stage_timings"]["whisper"] = time.time() - t0
print(f"Lang: {info.language} (p={info.language_probability:.2f}) | "
      f"{len(transcript)} segments | {PAYLOAD['stage_timings']['whisper']:.0f}s")
print("Sample:", transcript[0]["text"][:120] if transcript else "(empty)")
free_vram(whisper); vram_report()

# also language detection on full text (langdetect, CPU)
from langdetect import detect
full_text = " ".join(s["text"] for s in transcript)
try: PAYLOAD["langdetect"] = detect(full_text) if full_text.strip() else None
except Exception: PAYLOAD["langdetect"] = None
print("langdetect:", PAYLOAD["langdetect"])

# %% [markdown]
# ## Cell 6 — Stage 2A: Audio — diarization (pyannote) + features (librosa)

# %%
# Speaker diarization (optional — needs HF token + accepted terms for pyannote/speaker-diarization-3.1)
if CONFIG["ENABLE_DIARIZATION"] and HF_TOKEN:
    try:
        from pyannote.audio import Pipeline
        t0 = time.time()
        dia = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1", use_auth_token=HF_TOKEN)
        dia.to(torch.device(DEVICE))
        diar = dia(str(AUDIO_PATH))
        speakers = [{"speaker": spk, "start": round(turn.start, 2), "end": round(turn.end, 2)}
                    for turn, _, spk in diar.itertracks(yield_label=True)]
        PAYLOAD["speakers"] = speakers
        PAYLOAD["stage_timings"]["diarization"] = time.time() - t0
        n_spk = len(set(s["speaker"] for s in speakers))
        print(f"Diarization: {len(speakers)} turns, {n_spk} speakers")
        free_vram(dia)
    except Exception as e:
        print("Diarization skipped (accept terms at hf.co/pyannote/speaker-diarization-3.1):", e)
else:
    print("Diarization disabled.")

# Audio features (librosa, CPU)
import librosa
t0 = time.time()
y, sr = librosa.load(str(AUDIO_PATH), sr=16000)
rms = float(np.mean(librosa.feature.rms(y=y)))
intervals = librosa.effects.split(y, top_db=30)
voiced = sum((e - s) for s, e in intervals) / sr if len(intervals) else 0
words = len(full_text.split())
PAYLOAD["audio_features"] = {
    "rms_energy": round(rms, 4),
    "silence_ratio": round(1 - voiced / max(duration, 1e-6), 3),
    "words_per_minute": round(words / max(duration / 60, 1e-6), 1),
}
PAYLOAD["stage_timings"]["librosa"] = time.time() - t0
print("Audio features:", PAYLOAD["audio_features"])
free_vram(y); vram_report()

# %% [markdown]
# ## Cell 7 — Stage 2B: Visual — CLIP scene classification + YOLO objects

# %%
from PIL import Image
from transformers import CLIPProcessor, CLIPModel

t0 = time.time()
frame_analyses = [{"index": i, "time": round(frame_times[i], 1), "path": str(p),
                   "scene": None, "objects": [], "ocr": "", "caption": ""}
                  for i, p in enumerate(frame_files)]

# --- CLIP zero-shot scene labels ---
clip = CLIPModel.from_pretrained(CONFIG["CLIP_MODEL"]).to(DEVICE).eval()
clip_proc = CLIPProcessor.from_pretrained(CONFIG["CLIP_MODEL"])
with torch.no_grad():
    for fa in frame_analyses:
        img = Image.open(fa["path"]).convert("RGB")
        inp = clip_proc(text=SCENE_LABELS, images=img, return_tensors="pt", padding=True).to(DEVICE)
        logits = clip(**inp).logits_per_image.softmax(dim=1)[0]
        top = int(logits.argmax())
        fa["scene"] = SCENE_LABELS[top]
        fa["scene_conf"] = round(float(logits[top]), 3)
free_vram(clip, clip_proc)
print("CLIP done. Scene distribution:",
      {l: sum(1 for f in frame_analyses if f["scene"] == l) for l in SCENE_LABELS if any(f["scene"]==l for f in frame_analyses)})

# --- YOLOv8 object detection ---
from ultralytics import YOLO
yolo = YOLO(CONFIG["YOLO_MODEL"])
for fa in frame_analyses:
    res = yolo(fa["path"], verbose=False, device=0 if DEVICE=="cuda" else "cpu")[0]
    names = res.names
    fa["objects"] = sorted(set(names[int(c)] for c in res.boxes.cls.tolist())) if res.boxes is not None else []
free_vram(yolo)
all_objects = {}
for fa in frame_analyses:
    for o in fa["objects"]: all_objects[o] = all_objects.get(o, 0) + 1
print("Objects seen:", dict(sorted(all_objects.items(), key=lambda x:-x[1])[:10]))
vram_report()

# %% [markdown]
# ## Cell 8 — Stage 2B: Visual — OCR (EasyOCR) + captions (BLIP-2)

# %%
import easyocr
t0 = time.time()
# EasyOCR English (add 'ta','hi' in prod; they need extra model downloads)
reader = easyocr.Reader(["en"], gpu=(DEVICE == "cuda"))
for fa in frame_analyses:
    try:
        texts = reader.readtext(fa["path"], detail=0, paragraph=True)
        fa["ocr"] = " ".join(texts)[:500]
    except Exception:
        fa["ocr"] = ""
free_vram(reader)
ocr_blob = " ".join(f["ocr"] for f in frame_analyses if f["ocr"])
print(f"OCR done. {sum(1 for f in frame_analyses if f['ocr'])} frames had text.")
print("OCR sample:", ocr_blob[:200])

# BLIP-2 captioning (heaviest — captions a subset of frames)
if CONFIG["ENABLE_BLIP2"]:
    from transformers import Blip2Processor, Blip2ForConditionalGeneration
    blip_proc = Blip2Processor.from_pretrained(CONFIG["BLIP2_MODEL"])
    blip = Blip2ForConditionalGeneration.from_pretrained(
        CONFIG["BLIP2_MODEL"], torch_dtype=torch.float16).to(DEVICE).eval()
    # caption at most ~12 evenly spaced frames to save time
    step = max(1, len(frame_analyses) // 12)
    with torch.no_grad():
        for fa in frame_analyses[::step]:
            img = Image.open(fa["path"]).convert("RGB")
            inp = blip_proc(images=img, return_tensors="pt").to(DEVICE, torch.float16)
            out = blip.generate(**inp, max_new_tokens=40)
            fa["caption"] = blip_proc.batch_decode(out, skip_special_tokens=True)[0].strip()
    free_vram(blip, blip_proc)
    print("Captions sample:", [f["caption"] for f in frame_analyses if f["caption"]][:3])
else:
    print("BLIP-2 disabled.")

PAYLOAD["frame_analyses"] = frame_analyses
PAYLOAD["stage_timings"]["visual"] = time.time() - t0
vram_report()

# %% [markdown]
# ## Cell 9 — Stage 3: NLP enrichment (spaCy NER + KeyBERT + embeddings + BERTopic)

# %%
import spacy
from keybert import KeyBERT
from sentence_transformers import SentenceTransformer

t0 = time.time()
nlp = spacy.load("en_core_web_sm")
doc = nlp(full_text[:100000])
entities = sorted(set((ent.text, ent.label_) for ent in doc.ents))[:40]

embedder = SentenceTransformer(CONFIG["EMBED_MODEL"], device=DEVICE)

# Keyword extraction. KeyBERT breaks on sentence-transformers v5 (its word list gets
# misrouted as an 'audio' modality), so fall back to a spaCy noun-chunk frequency
# extractor — dependency-light and good enough to seed the LLM prompt.
def fallback_keywords(spacy_doc, top_n=20):
    from collections import Counter
    chunks = [c.text.lower().strip() for c in spacy_doc.noun_chunks]
    chunks = [c for c in chunks if 2 <= len(c) <= 40 and not c.isspace()]
    cnt = Counter(chunks)
    n = sum(cnt.values()) or 1
    return [(term, round(c / n, 3)) for term, c in cnt.most_common(top_n)]

keywords = []
if full_text.strip():
    try:
        kw = KeyBERT(model=embedder)
        keywords = kw.extract_keywords(full_text, keyphrase_ngram_range=(1, 2),
                                       stop_words="english", top_n=20)
    except Exception as e:
        print("KeyBERT unavailable (sentence-transformers v5 incompat); spaCy fallback:", str(e)[:100])
        keywords = fallback_keywords(doc)

PAYLOAD["nlp"] = {
    "entities": [{"text": t, "label": l} for t, l in entities],
    "keywords": [{"term": k, "score": round(s, 3)} for k, s in keywords],
}
print("Entities:", PAYLOAD["nlp"]["entities"][:8])
print("Keywords:", [k["term"] for k in PAYLOAD["nlp"]["keywords"]][:12])

# Build 30s transcript windows + embeddings (reused by segmentation + BERTopic)
def build_windows(transcript, win=CONFIG["WINDOW_SEC"]):
    if not transcript: return []
    end_t = transcript[-1]["end"]
    windows, t = [], 0.0
    while t < end_t:
        chunk = " ".join(s["text"] for s in transcript if t <= s["start"] < t + win)
        windows.append({"start": t, "end": min(t + win, end_t), "text": chunk})
        t += win
    return [w for w in windows if w["text"].strip()]

windows = build_windows(transcript)
win_texts = [w["text"] for w in windows]
win_emb = embedder.encode(win_texts, normalize_embeddings=True) if win_texts else np.zeros((0, 384))
print(f"{len(windows)} transcript windows embedded.")

# BERTopic (optional; needs enough windows)
if CONFIG["ENABLE_BERTOPIC"] and len(windows) >= 8:
    try:
        from bertopic import BERTopic
        tm = BERTopic(embedding_model=embedder, min_topic_size=2, verbose=False)
        topics, _ = tm.fit_transform(win_texts, embeddings=np.array(win_emb))
        info = tm.get_topic_info()
        PAYLOAD["nlp"]["bertopic"] = info[["Topic", "Count", "Name"]].to_dict("records")
        print("BERTopic topics:", PAYLOAD["nlp"]["bertopic"][:5])
    except Exception as e:
        print("BERTopic skipped:", e)
else:
    print("BERTopic skipped (need >=8 windows).")

PAYLOAD["stage_timings"]["nlp"] = time.time() - t0
free_vram(nlp); vram_report()

# %% [markdown]
# ## Cell 10 — Stage 5: Temporal segmentation (cosine drop + kneed)
# We segment first, then tag each segment with the LLM (Stage 4) in the next cell.

# %%
from kneed import KneeLocator
t0 = time.time()

def segment(windows, win_emb):
    if len(windows) <= 1:
        return [{"start": 0.0, "end": PAYLOAD.get("duration", windows[-1]["end"] if windows else 0)}]
    # cosine similarity between adjacent windows
    sims = [float(np.dot(win_emb[i], win_emb[i+1])) for i in range(len(win_emb)-1)]
    drops = [1 - s for s in sims]
    # find threshold via knee on sorted drops
    thresh = CONFIG["SIM_DROP_FALLBACK"]
    try:
        sd = sorted(drops)
        kn = KneeLocator(range(len(sd)), sd, curve="convex", direction="increasing")
        if kn.knee is not None:
            thresh = max(sd[kn.knee], 0.15)
    except Exception:
        pass
    # boundaries where drop exceeds threshold
    boundaries = [0]
    for i, d in enumerate(drops):
        if d >= thresh:
            boundaries.append(i + 1)
    boundaries.append(len(windows))
    boundaries = sorted(set(boundaries))
    # build segments + enforce min duration
    segs = []
    for a, b in zip(boundaries[:-1], boundaries[1:]):
        segs.append({"start": windows[a]["start"], "end": windows[b-1]["end"]})
    merged = []
    for s in segs:
        if merged and (s["end"] - merged[-1]["start"]) and (s["start"] - merged[-1]["start"]) < CONFIG["MIN_SEGMENT_SEC"]:
            merged[-1]["end"] = s["end"]
        else:
            merged.append(s)
    return merged

segs = segment(windows, win_emb)
# attach transcript text + visual signals per segment
for s in segs:
    s["text"] = " ".join(t["text"] for t in transcript if s["start"] <= t["start"] < s["end"])
    seg_frames = [f for f in frame_analyses if s["start"] <= f["time"] < s["end"]]
    s["scenes"] = sorted(set(f["scene"] for f in seg_frames if f["scene"]))
    s["objects"] = sorted(set(o for f in seg_frames for o in f["objects"]))
    s["ocr"] = " ".join(f["ocr"] for f in seg_frames if f["ocr"])[:600]
    s["captions"] = [f["caption"] for f in seg_frames if f["caption"]][:3]
PAYLOAD["segments"] = segs
PAYLOAD["stage_timings"]["segmentation"] = time.time() - t0
print(f"{len(segs)} segments:")
for i, s in enumerate(segs):
    print(f"  seg {i}: {s['start']:.0f}-{s['end']:.0f}s  scenes={s['scenes']}")

# %% [markdown]
# ## Cell 11 — Stage 4: LLM semantic fusion (Qwen 4-bit, guided JSON)
# Synthesises transcript + visual + NLP signals into structured tags **per segment**.

# %%
from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig
t0 = time.time()
bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_compute_dtype=torch.float16,
                         bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True)
tok = AutoTokenizer.from_pretrained(CONFIG["LLM_MODEL"])
llm = AutoModelForCausalLM.from_pretrained(CONFIG["LLM_MODEL"], quantization_config=bnb,
                                           device_map="auto", torch_dtype=torch.float16)

SCHEMA_HINT = """Return ONLY valid JSON with these keys:
{"topic": str, "subtopics": [str], "content_type": "lecture|tutorial|demo|discussion|animation",
 "difficulty": "beginner|intermediate|advanced|expert", "grade_level": str, "subject": str,
 "summary": str, "tags": [str], "speaker_role": "teacher|student|narrator|unknown",
 "language": str, "has_visual_content": bool, "confidence": float}"""

# Inject Katbook domain context (the doc's single highest-impact lever). Edit for your taxonomy.
DOMAIN_CONTEXT = ("Katbook is an EdTech platform. Tag content using school/college subject "
                  "taxonomy (e.g. Physics, Chemistry, Biology, Mathematics), grade levels, and "
                  "precise concept names. Prefer curriculum-specific tags over generic ones.")

def fuse(seg, lang, kw_terms):
    prompt = f"""{DOMAIN_CONTEXT}

Pre-computed keywords: {kw_terms}
Detected scenes: {seg['scenes']}
Detected objects: {seg['objects']}
On-screen text (OCR): {seg['ocr'][:300]}
Frame captions: {seg['captions']}
Transcript:
\"\"\"{seg['text'][:2500]}\"\"\"

{SCHEMA_HINT}"""
    msgs = [{"role": "system", "content": "You are a precise educational video tagging engine."},
            {"role": "user", "content": prompt}]
    text = tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
    inp = tok(text, return_tensors="pt").to(llm.device)
    with torch.no_grad():
        out = llm.generate(**inp, max_new_tokens=CONFIG.get("LLM_MAX_NEW_TOKENS", 400),
                           do_sample=False, pad_token_id=tok.eos_token_id)
    raw = tok.decode(out[0][inp.input_ids.shape[1]:], skip_special_tokens=True)
    t = re.sub(r"```$", "", re.sub(r"^```(?:json)?", "", raw.strip()).strip()).strip()
    m = re.search(r"\{.*", t, re.DOTALL)
    if m:
        js = m.group(0)
        for cand in (js, js + "}", js + '"}', js + '"}}', js[:js.rfind("}") + 1] if "}" in js else js):
            try:
                return json.loads(cand)
            except Exception:
                pass
    return {"_parse_error": raw[:300]}

kw_terms = [k["term"] for k in PAYLOAD["nlp"].get("keywords", [])]
for i, s in enumerate(PAYLOAD["segments"]):
    s["llm"] = fuse(s, PAYLOAD["language"], kw_terms)
    print(f"seg {i}: topic={s['llm'].get('topic')!r} tags={s['llm'].get('tags')}")

PAYLOAD["stage_timings"]["llm"] = time.time() - t0
free_vram(llm, tok); vram_report()

# segment summary embeddings for vector search
seg_summaries = [(s.get("llm", {}).get("summary") or s["text"][:300]) for s in PAYLOAD["segments"]]
seg_emb = embedder.encode(seg_summaries, normalize_embeddings=True) if seg_summaries else np.zeros((0,384))
print("Segment embeddings:", seg_emb.shape)

# %% [markdown]
# ## Cell 12 — Stage 6: Storage → Postgres (pgvector) + full-text + Qdrant

# %%
if DATABASE_URL:
    from sqlalchemy import create_engine, text as sqltext
    from pgvector.sqlalchemy import Vector  # noqa
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    DIM = int(seg_emb.shape[1]) if seg_emb.shape[0] else 384

    with engine.begin() as cx:
        cx.execute(sqltext("CREATE EXTENSION IF NOT EXISTS vector"))
        cx.execute(sqltext("""
            CREATE TABLE IF NOT EXISTS videos (
                video_id UUID PRIMARY KEY, source_path TEXT, duration FLOAT,
                language TEXT, audio_features JSONB, nlp JSONB,
                stage_timings JSONB, created_at TIMESTAMPTZ DEFAULT now())"""))
        cx.execute(sqltext(f"""
            CREATE TABLE IF NOT EXISTS segments (
                id SERIAL PRIMARY KEY, video_id UUID REFERENCES videos(video_id),
                seg_index INT, start_sec FLOAT, end_sec FLOAT,
                transcript TEXT, scenes JSONB, objects JSONB, ocr TEXT,
                llm JSONB, embedding vector({DIM}),
                fts tsvector GENERATED ALWAYS AS (to_tsvector('english', coalesce(transcript,''))) STORED)"""))
        cx.execute(sqltext("CREATE INDEX IF NOT EXISTS seg_fts_idx ON segments USING GIN(fts)"))

        # upsert video row
        cx.execute(sqltext("""INSERT INTO videos(video_id,source_path,duration,language,audio_features,nlp,stage_timings)
            VALUES (:vid,:sp,:dur,:lang,:af,:nlp,:st)
            ON CONFLICT (video_id) DO UPDATE SET stage_timings=:st"""),
            {"vid": PAYLOAD["video_id"], "sp": PAYLOAD["source_path"],
             "dur": float(PAYLOAD["duration"]) if PAYLOAD.get("duration") is not None else None,
             "lang": PAYLOAD["language"], "af": json.dumps(PAYLOAD["audio_features"]),
             "nlp": json.dumps(PAYLOAD["nlp"]), "st": json.dumps(PAYLOAD["stage_timings"])})
        # clear old segments for this video, then insert
        # NOTE: cast start/end to native float — faster-whisper emits numpy floats,
        # which psycopg2 can't adapt (raises "schema np does not exist").
        cx.execute(sqltext("DELETE FROM segments WHERE video_id=:v"), {"v": PAYLOAD["video_id"]})
        for i, s in enumerate(PAYLOAD["segments"]):
            emb = seg_emb[i].tolist() if i < len(seg_emb) else [0.0]*DIM
            cx.execute(sqltext("""INSERT INTO segments
                (video_id,seg_index,start_sec,end_sec,transcript,scenes,objects,ocr,llm,embedding)
                VALUES (:v,:i,:a,:b,:tr,:sc,:ob,:ocr,:llm,:emb)"""),
                {"v": PAYLOAD["video_id"], "i": i, "a": float(s["start"]), "b": float(s["end"]),
                 "tr": s["text"], "sc": json.dumps(s["scenes"]), "ob": json.dumps(s["objects"]),
                 "ocr": s["ocr"], "llm": json.dumps(s.get("llm", {})), "emb": str(emb)})
    print(f"Stored 1 video + {len(PAYLOAD['segments'])} segments in Postgres.")
else:
    print("No DATABASE_URL — skipped Postgres write.")

# Qdrant local vector DB (in addition to pgvector) — demonstrates the doc's vector store
if CONFIG["ENABLE_QDRANT"] and seg_emb.shape[0]:
    from qdrant_client import QdrantClient
    from qdrant_client.models import VectorParams, Distance, PointStruct
    qc = QdrantClient(path=str(WORK / "qdrant_db"))  # local persisted to /kaggle/working
    qc.recreate_collection("segments",
        vectors_config=VectorParams(size=int(seg_emb.shape[1]), distance=Distance.COSINE))
    qc.upsert("segments", points=[
        PointStruct(id=i, vector=seg_emb[i].tolist(),
                    payload={"video_id": PAYLOAD["video_id"], "seg_index": i,
                             "topic": PAYLOAD["segments"][i].get("llm", {}).get("topic"),
                             "start": float(PAYLOAD["segments"][i]["start"])})
        for i in range(len(seg_emb))])
    print("Qdrant local collection 'segments' upserted.")

PAYLOAD["status"] = "complete"

# %% [markdown]
# ## Cell 13 — Verify: read back + semantic search + full-text search

# %%
if DATABASE_URL:
    from sqlalchemy import text as sqltext
    with engine.connect() as cx:
        rows = cx.execute(sqltext("""SELECT seg_index, start_sec, end_sec,
            llm->>'topic' AS topic, llm->'tags' AS tags
            FROM segments WHERE video_id=:v ORDER BY seg_index"""),
            {"v": PAYLOAD["video_id"]}).fetchall()
        print("=== Stored segments ===")
        for r in rows:
            print(f"  [{r.start_sec:.0f}-{r.end_sec:.0f}s] {r.topic} | tags={r.tags}")

        # full-text search demo (Elasticsearch substitute)
        q = "energy"   # change to a word likely in your video
        fts = cx.execute(sqltext("""SELECT seg_index, ts_rank(fts, plainto_tsquery('english',:q)) AS rank
            FROM segments WHERE video_id=:v AND fts @@ plainto_tsquery('english',:q)
            ORDER BY rank DESC"""), {"q": q, "v": PAYLOAD["video_id"]}).fetchall()
        print(f"\n=== Full-text search '{q}' ===", [(r.seg_index, round(r.rank,3)) for r in fts])

# semantic search demo via pgvector
if DATABASE_URL and seg_emb.shape[0]:
    query = "explain the main concept"   # try any natural-language query
    qv = embedder.encode([query], normalize_embeddings=True)[0].tolist()
    with engine.connect() as cx:
        sem = cx.execute(sqltext("""SELECT seg_index, llm->>'topic' AS topic,
            1 - (embedding <=> :qv) AS score FROM segments
            WHERE video_id=:v ORDER BY embedding <=> :qv LIMIT 5"""),
            {"qv": str(qv), "v": PAYLOAD["video_id"]}).fetchall()
        print(f"\n=== Semantic search '{query}' ===")
        for r in sem: print(f"  seg {r.seg_index}: {r.topic} (score={r.score:.3f})")

# Save the full payload as a downloadable artifact too
with open(WORK / "payload.json", "w") as f:
    json.dump(PAYLOAD, f, indent=2, default=str)
print("\nPipeline complete. Timings:", PAYLOAD["stage_timings"])
print("payload.json saved to /kaggle/working (downloadable).")

# %% [markdown]
# ## Cell 13b — Clean structured results export (grade / difficulty / subject / objects …)
# `payload.json` is the full verbose dump. This writes a tidy, flat `results_<id>.json`
# (one summary block + one row per segment) — every field already exists, we just surface
# them: topic, difficulty, **subject**, **grade**, tags, summary, confidence, dominant_scene,
# objects_detected. This is the human-readable artifact to share / load into the DB / show.

# %%
import json, platform
from pathlib import Path
from collections import Counter

WORK = Path("/kaggle/working"); WORK.mkdir(exist_ok=True, parents=True)

def _dominant_scene_from_frames(seg):
    # richest source: most frequent CLIP scene among the segment's frames (in-memory only)
    try:
        fr = [f for f in frame_analyses if seg["start"] <= f["time"] < seg["end"] and f.get("scene")]
        if fr:
            return Counter(f["scene"] for f in fr).most_common(1)[0][0]
    except NameError:
        pass
    return (seg.get("scenes") or [None])[0]

def _row(i, start, end, llm, dominant, objects):
    llm = llm or {}
    return {
        "segment": i, "start": round(float(start), 1), "end": round(float(end), 1),
        "topic": llm.get("topic"), "difficulty": llm.get("difficulty"),
        "subject": llm.get("subject"), "grade": llm.get("grade_level"),
        "content_type": llm.get("content_type"), "tags": llm.get("tags", []),
        "summary": llm.get("summary"), "confidence": llm.get("confidence"),
        "dominant_scene": dominant, "objects_detected": objects,
    }

# --- Build from in-memory PAYLOAD if the pipeline ran this session; else rebuild from Postgres ---
try:
    PAYLOAD
    _src = "memory"
except NameError:
    _src = "db"

if _src == "memory":
    from datetime import datetime, timezone
    results = {
        "video_id": PAYLOAD["video_id"][:8], "source": PAYLOAD["source_path"],
        "processed_at": datetime.now(timezone.utc).isoformat(),
        "os": f"{platform.system()} {platform.release()}", "python": platform.python_version(),
        "duration_sec": round(float(PAYLOAD.get("duration") or 0), 2),
        "language": PAYLOAD.get("language"), "segment_count": len(PAYLOAD["segments"]),
        "pipeline_time_sec": round(sum(PAYLOAD.get("stage_timings", {}).values()), 1),
        "segments": [_row(i, s["start"], s["end"], s.get("llm"),
                          _dominant_scene_from_frames(s), s.get("objects", []))
                     for i, s in enumerate(PAYLOAD["segments"], start=1)],
    }
else:
    # kernel was restarted — pull the most recent video straight from cloud Postgres
    print("PAYLOAD not in memory; rebuilding export from Postgres.")
    from sqlalchemy import create_engine, text as sqltext
    from kaggle_secrets import UserSecretsClient
    _u = UserSecretsClient().get_secret("DATABASE_URL")
    if _u.startswith("postgres://"):    _u = _u.replace("postgres://", "postgresql+psycopg2://", 1)
    elif _u.startswith("postgresql://"): _u = _u.replace("postgresql://", "postgresql+psycopg2://", 1)
    engine = create_engine(_u, pool_pre_ping=True)
    _j = lambda x: x if isinstance(x, (list, dict)) else (json.loads(x) if x else {})
    with engine.connect() as cx:
        v = cx.execute(sqltext("""SELECT video_id, source_path, duration, language,
            stage_timings, created_at FROM videos ORDER BY created_at DESC LIMIT 1""")).mappings().first()
        if not v:
            raise RuntimeError("No videos in Postgres yet — run the pipeline + Cell 12 first.")
        segs = cx.execute(sqltext("""SELECT seg_index, start_sec, end_sec, scenes, objects, llm
            FROM segments WHERE video_id=:v ORDER BY seg_index"""), {"v": str(v["video_id"])}).mappings().all()
    st = _j(v["stage_timings"])
    results = {
        "video_id": str(v["video_id"])[:8], "source": v["source_path"],
        "processed_at": v["created_at"].isoformat() if v["created_at"] else None,
        "os": f"{platform.system()} {platform.release()}", "python": platform.python_version(),
        "duration_sec": round(float(v["duration"] or 0), 2), "language": v["language"],
        "segment_count": len(segs),
        "pipeline_time_sec": round(sum(st.values()), 1) if isinstance(st, dict) and st else None,
        "segments": [_row(i, s["start_sec"], s["end_sec"], _j(s["llm"]),
                          (_j(s["scenes"]) or [None])[0], _j(s["objects"]))
                     for i, s in enumerate(segs, start=1)],
    }

results_path = WORK / f"results_{results['video_id']}.json"
with open(results_path, "w") as f:
    json.dump(results, f, indent=2, default=str)
print(json.dumps(results, indent=2, default=str))   # full JSON, no truncation
print("\nSaved clean export:", results_path)

# %% [markdown]
# ## Cell 14 — Search UI (Gradio): the "platform" layer
# A small app over Postgres so a human can actually *use* the index: type a natural-language
# query → ranked video segments via **hybrid search** (pgvector semantic + tsvector full-text),
# with **tag filters** (subject / grade / content_type) read from the LLM fusion output.
#
# Self-contained: it reconnects the DB engine and reloads the embedder if they were freed,
# so you can run this cell on its own after a kernel restart (no need to re-run the pipeline).
# On Kaggle, `launch(share=True)` prints a public *.gradio.live link — open it in a new tab.

# %%
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "gradio>=4.0"], check=False)
import gradio as gr

# --- ensure secret + DB engine + embedder exist even after a fresh kernel ---
# (cloud Postgres is persistent, so this cell runs standalone — no need to re-run the pipeline)
try:
    DATABASE_URL  # set by Cell 3 if the pipeline ran this session
except NameError:
    from kaggle_secrets import UserSecretsClient
    _u = UserSecretsClient().get_secret("DATABASE_URL")
    DATABASE_URL = (_u.replace("postgres://", "postgresql+psycopg2://", 1)
                    if _u.startswith("postgres://") and not _u.startswith("postgresql://")
                    else _u.replace("postgresql://", "postgresql+psycopg2://", 1)
                    if _u.startswith("postgresql://") else _u)
if not DATABASE_URL:
    raise RuntimeError("No DATABASE_URL secret — add it under Settings → Secrets, then re-run.")
from sqlalchemy import create_engine, text as sqltext
try:
    engine  # reuse if pipeline already created it
except NameError:
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
try:
    embedder
except NameError:
    from sentence_transformers import SentenceTransformer
    embedder = SentenceTransformer(CONFIG["EMBED_MODEL"], device=DEVICE)

# --- distinct tag values to populate the filter dropdowns ---
def _distinct(json_key):
    with engine.connect() as cx:
        rows = cx.execute(sqltext(
            f"SELECT DISTINCT llm->>'{json_key}' AS v FROM segments "
            f"WHERE llm->>'{json_key}' IS NOT NULL ORDER BY 1")).fetchall()
    return ["(any)"] + [r.v for r in rows if r.v]

def _refresh_choices():
    return _distinct("subject"), _distinct("grade_level"), _distinct("content_type")

# --- hybrid search: blend pgvector cosine score with full-text rank ---
def search(query, subject, grade, ctype, mode, top_k):
    query = (query or "").strip()
    if not query:
        return "Type a query above.", None
    qv = embedder.encode([query], normalize_embeddings=True)[0].tolist()
    filters, params = [], {"qv": str(qv), "q": query, "k": int(top_k)}
    if subject and subject != "(any)":
        filters.append("llm->>'subject' = :subject"); params["subject"] = subject
    if grade and grade != "(any)":
        filters.append("llm->>'grade_level' = :grade"); params["grade"] = grade
    if ctype and ctype != "(any)":
        filters.append("llm->>'content_type' = :ctype"); params["ctype"] = ctype
    where = (" AND " + " AND ".join(filters)) if filters else ""

    # semantic, full-text, and a 0.6/0.4 hybrid blend of the two normalized scores
    if mode == "Semantic (pgvector)":
        sql = f"""SELECT video_id, seg_index, start_sec, end_sec, llm->>'topic' AS topic,
            llm->>'summary' AS summary, llm->'tags' AS tags,
            1 - (embedding <=> :qv) AS score
            FROM segments WHERE TRUE {where}
            ORDER BY embedding <=> :qv LIMIT :k"""
    elif mode == "Full-text (tsvector)":
        sql = f"""SELECT video_id, seg_index, start_sec, end_sec, llm->>'topic' AS topic,
            llm->>'summary' AS summary, llm->'tags' AS tags,
            ts_rank(fts, plainto_tsquery('english', :q)) AS score
            FROM segments WHERE fts @@ plainto_tsquery('english', :q) {where}
            ORDER BY score DESC LIMIT :k"""
    else:  # Hybrid
        sql = f"""WITH s AS (
            SELECT video_id, seg_index, start_sec, end_sec, llm,
                   1 - (embedding <=> :qv) AS sem,
                   ts_rank(fts, plainto_tsquery('english', :q)) AS fts_rank
            FROM segments WHERE TRUE {where})
            SELECT video_id, seg_index, start_sec, end_sec, llm->>'topic' AS topic,
                   llm->>'summary' AS summary, llm->'tags' AS tags,
                   0.6*sem + 0.4*(fts_rank / NULLIF(MAX(fts_rank) OVER (),0)) AS score
            FROM s ORDER BY score DESC NULLS LAST LIMIT :k"""

    with engine.connect() as cx:
        rows = cx.execute(sqltext(sql), params).fetchall()
    if not rows:
        return "No matching segments. Loosen the filters or try another query.", None

    md = [f"### {len(rows)} result(s) for **{query}**"]
    table = []
    for r in rows:
        ts = f"{int(r.start_sec//60)}:{int(r.start_sec%60):02d}–{int(r.end_sec//60)}:{int(r.end_sec%60):02d}"
        tags = ", ".join(json.loads(r.tags)) if r.tags else ""
        md.append(f"**[{ts}]  {r.topic or '(untagged)'}**  · score `{float(r.score or 0):.3f}`  \n"
                  f"{(r.summary or '')[:240]}  \n*tags:* {tags}")
        table.append([r.seg_index, ts, r.topic, round(float(r.score or 0), 3)])
    return "\n\n".join(md), table

with gr.Blocks(title="Katbook Video Intelligence — Search") as demo:
    gr.Markdown("# 🎬 Katbook Video Intelligence — Segment Search\n"
                "Search inside processed videos by meaning, keyword, or both.")
    with gr.Row():
        q = gr.Textbox(label="Query", placeholder="e.g. how does photosynthesis work?", scale=4)
        go = gr.Button("Search", variant="primary", scale=1)
    with gr.Row():
        f_subj = gr.Dropdown(label="Subject", choices=_distinct("subject"), value="(any)")
        f_grade = gr.Dropdown(label="Grade", choices=_distinct("grade_level"), value="(any)")
        f_type = gr.Dropdown(label="Content type", choices=_distinct("content_type"), value="(any)")
        f_mode = gr.Radio(["Hybrid", "Semantic (pgvector)", "Full-text (tsvector)"],
                          value="Hybrid", label="Mode")
        f_k = gr.Slider(1, 20, value=5, step=1, label="Top K")
    out_md = gr.Markdown()
    out_tbl = gr.Dataframe(headers=["seg", "time", "topic", "score"], label="Ranked segments")
    go.click(search, [q, f_subj, f_grade, f_type, f_mode, f_k], [out_md, out_tbl])
    q.submit(search, [q, f_subj, f_grade, f_type, f_mode, f_k], [out_md, out_tbl])

# Non-blocking launch: prevent_thread_lock=True so "Run All" / "Save & Run All" does NOT
# hang here — the cell returns immediately and the run completes, so your pipeline output
# (results_<id>.json from Cell 13b, Postgres rows from Cell 12) is saved and downloadable.
# The share link stays live while the kernel runs; in a committed run it just starts & exits.
demo.launch(share=True, prevent_thread_lock=True)
print("Search UI launched (non-blocking). Open the *.gradio.live link above while the kernel runs.")
print("Pipeline output is already saved to /kaggle/working/ (results_<id>.json, payload.json).")
