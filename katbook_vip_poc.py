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
print("Config loaded. VIDEO_PATH =", CONFIG["VIDEO_PATH"])

# %% [markdown]
# ## Cell 1 — Install dependencies
# Kaggle ships torch/transformers; we add the pipeline-specific libs. (~3-5 min first run.)

# %%
import subprocess, sys
def pip(*pkgs):
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", *pkgs], check=False)

pip("faster-whisper==1.0.3")
pip("pyannote.audio==3.3.2")
pip("langdetect", "librosa", "kneed")
pip("ultralytics==8.3.0")
pip("easyocr==1.7.2")
pip("keybert", "sentence-transformers", "bertopic")
pip("qdrant-client")
pip("psycopg2-binary", "sqlalchemy>=2.0", "pgvector")
pip("bitsandbytes>=0.43", "accelerate>=0.30")
pip("ffmpeg-python")
# spaCy small English model (en_core_web_trf is better but heavy; swap in prod)
subprocess.run([sys.executable, "-m", "spacy", "download", "en_core_web_sm"], check=False)
print("Installs done.")

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

# The single growing payload that flows through every stage (the doc's JobPayload)
PAYLOAD = {
    "video_id": None, "source_path": CONFIG["VIDEO_PATH"],
    "transcript": [], "speakers": [], "language": None,
    "audio_features": {}, "frame_analyses": [], "nlp": {},
    "segments": [], "status": "processing", "stage_timings": {},
}

import uuid
PAYLOAD["video_id"] = str(uuid.uuid4())
print("video_id:", PAYLOAD["video_id"])

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
# ## Cell 4 — Stage 1: Ingest & Demux (ffmpeg)
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
from faster_whisper import WhisperModel
t0 = time.time()
whisper = WhisperModel(CONFIG["WHISPER_MODEL"], device=DEVICE, compute_type="float16")
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
kw = KeyBERT(model=embedder)
keywords = kw.extract_keywords(full_text, keyphrase_ngram_range=(1, 2),
                               stop_words="english", top_n=20) if full_text.strip() else []

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
        out = llm.generate(**inp, max_new_tokens=400, do_sample=False,
                           pad_token_id=tok.eos_token_id)
    raw = tok.decode(out[0][inp.input_ids.shape[1]:], skip_special_tokens=True)
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    try:
        return json.loads(m.group(0)) if m else {"_parse_error": raw[:300]}
    except Exception:
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
            {"vid": PAYLOAD["video_id"], "sp": PAYLOAD["source_path"], "dur": PAYLOAD.get("duration"),
             "lang": PAYLOAD["language"], "af": json.dumps(PAYLOAD["audio_features"]),
             "nlp": json.dumps(PAYLOAD["nlp"]), "st": json.dumps(PAYLOAD["stage_timings"])})
        # clear old segments for this video, then insert
        cx.execute(sqltext("DELETE FROM segments WHERE video_id=:v"), {"v": PAYLOAD["video_id"]})
        for i, s in enumerate(PAYLOAD["segments"]):
            emb = seg_emb[i].tolist() if i < len(seg_emb) else [0.0]*DIM
            cx.execute(sqltext("""INSERT INTO segments
                (video_id,seg_index,start_sec,end_sec,transcript,scenes,objects,ocr,llm,embedding)
                VALUES (:v,:i,:a,:b,:tr,:sc,:ob,:ocr,:llm,:emb)"""),
                {"v": PAYLOAD["video_id"], "i": i, "a": s["start"], "b": s["end"],
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
                             "start": PAYLOAD["segments"][i]["start"]})
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
