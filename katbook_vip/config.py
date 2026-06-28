"""
config.py — single source of configuration for the Katbook VIP pipeline.

Design goals
------------
* One small CONFIG dict you actually edit.
* SPEED PROFILES ("fast" | "balanced" | "quality") flip every model/sampling knob
  together so you never tune ten settings by hand. Free Kaggle T4 -> use "fast".
* Everything is overridable by environment variable, so the same code runs on
  Kaggle, in a local CPU smoke-test, or in CI without editing the file.

Nothing here loads a model or touches the GPU; importing this module is free.
"""
from __future__ import annotations
import os


# --------------------------------------------------------------------------- #
# What to process + where things live (the bits you change per run).
# --------------------------------------------------------------------------- #
BASE = {
    # INPUT --------------------------------------------------------------- #
    # On Kaggle every .mp4 under /kaggle/input is auto-discovered; you do not
    # edit a path. Locally, point VIDEO_GLOB at a folder of test clips.
    "VIDEO_GLOB": os.environ.get("KVIP_VIDEO_GLOB", "/kaggle/input/**/*.mp4"),

    # WHICH videos the run processes (a numbered list is printed at startup):
    #   "all"                 -> every discovered video
    #   "first"               -> only the first
    #   3                     -> ONLY video #3 from the printed list (unambiguous)
    #   "pendulum"            -> every filename CONTAINING this text
    #   "exact name.mp4"      -> only the file whose name equals this exactly
    "PROCESS": os.environ.get("KVIP_PROCESS", "all"),

    # Re-running never duplicates or redoes a video already in Postgres.
    # Set False to FORCE reprocessing (e.g. after changing the prompt/models).
    "SKIP_EXISTING": os.environ.get("KVIP_SKIP_EXISTING", "1") != "0",

    # OUTPUT -------------------------------------------------------------- #
    "WORK_DIR": os.environ.get("KVIP_WORK_DIR", "/kaggle/working"),
    "RESULTS_SUBDIR": "results",        # clean per-video JSON lands here
    "CHECKPOINT_SUBDIR": "checkpoints",  # resume cache (expensive stages)

    # SPEED PROFILE: "fast" (free T4, ~2-3 min/video) | "balanced" | "quality"
    "PROFILE": os.environ.get("KVIP_PROFILE", "fast"),

    # OCR scripts. English is the most reliable; add an Indic script to read
    # on-screen Tamil/Hindi. EasyOCR sometimes fails to load Tamil weights
    # (state_dict mismatch) -> the pipeline falls back to English automatically.
    # The spoken TRANSCRIPT (Whisper, fully multilingual) drives tags, so this
    # only matters for SILENT videos with non-English on-screen text.
    "OCR_LANGS": os.environ.get("KVIP_OCR_LANGS", "en").split(","),

    # ROUTER thresholds (voice vs no-voice detection) -------------------- #
    # Mean RMS (dB) below this == effectively silent / no narration.
    # Validated: silent clip ~ -99 dB, narrated clips ~ -20..-30 dB.
    "SILENCE_DB": float(os.environ.get("KVIP_SILENCE_DB", "-50")),
    # Minimum total spoken seconds for the VOICE path; below this -> SILENT path.
    "MIN_SPEECH_SEC": float(os.environ.get("KVIP_MIN_SPEECH_SEC", "3")),

    # SEGMENTATION ------------------------------------------------------- #
    "WINDOW_SEC": 30,         # transcript window for embeddings
    "MIN_SEGMENT_SEC": 45,    # do not emit segments shorter than this
    "MAX_SEGMENTS": 12,       # hard cap on segments/video (caps LLM calls)
    "SIM_DROP_FALLBACK": 0.25,

    # STORAGE ------------------------------------------------------------ #
    # Set via env/secret. The pipeline runs JSON-only if absent.
    "DATABASE_URL": os.environ.get("DATABASE_URL"),
    "ENABLE_DB": os.environ.get("KVIP_ENABLE_DB", "1") != "0",

    # Per-segment LLM output budget (enough to finish strict JSON).
    "LLM_MAX_NEW_TOKENS": int(os.environ.get("KVIP_LLM_TOKENS", "420")),
}


# --------------------------------------------------------------------------- #
# Speed profiles. Each flips models + sampling together.
# "fast" is tuned for a single free T4 (16 GB) at ~2-3 min/video.
# --------------------------------------------------------------------------- #
PROFILES = {
    "fast": {
        "WHISPER_MODEL": "medium",
        "CLIP_MODEL": "openai/clip-vit-base-patch32",
        "YOLO_MODEL": "yolov8n.pt",
        "BLIP2_MODEL": "Salesforce/blip2-opt-2.7b",
        "LLM_MODEL": "Qwen/Qwen2.5-7B-Instruct",
        "EMBED_MODEL": "sentence-transformers/all-MiniLM-L6-v2",
        # frame budgets: voiced needs few (transcript leads); silent needs more
        "MAX_FRAMES_VOICE": 12,
        "MAX_FRAMES_SILENT": 24,
        "CAPTION_FRAMES": 6,      # BLIP-2 caption budget (silent path)
        "USE_SCENE_CUTS": True,
        "WHISPER_BEAM": 1,
    },
    "balanced": {
        "WHISPER_MODEL": "medium",
        "CLIP_MODEL": "openai/clip-vit-base-patch32",
        "YOLO_MODEL": "yolov8s.pt",
        "BLIP2_MODEL": "Salesforce/blip2-opt-2.7b",
        "LLM_MODEL": "Qwen/Qwen2.5-7B-Instruct",
        "EMBED_MODEL": "sentence-transformers/all-MiniLM-L6-v2",
        "MAX_FRAMES_VOICE": 18,
        "MAX_FRAMES_SILENT": 32,
        "CAPTION_FRAMES": 10,
        "USE_SCENE_CUTS": True,
        "WHISPER_BEAM": 3,
    },
    "quality": {
        "WHISPER_MODEL": "large-v3",
        "CLIP_MODEL": "openai/clip-vit-large-patch14",
        "YOLO_MODEL": "yolov8m.pt",
        "BLIP2_MODEL": "Salesforce/blip2-opt-2.7b",
        "LLM_MODEL": "Qwen/Qwen2.5-7B-Instruct",
        "EMBED_MODEL": "sentence-transformers/all-MiniLM-L6-v2",
        "MAX_FRAMES_VOICE": 30,
        "MAX_FRAMES_SILENT": 48,
        "CAPTION_FRAMES": 16,
        "USE_SCENE_CUTS": True,
        "WHISPER_BEAM": 5,
    },
}


# CLIP zero-shot scene vocabulary. The "real-world vs synthetic" split below
# decides whether YOLO runs (it hallucinates on animation/diagrams) and whether
# OCR runs (text-heavy frames only). Tune to your content.
SCENE_LABELS = [
    "teacher at a whiteboard", "slide presentation", "laboratory experiment",
    "student discussion", "diagram explanation", "demonstration with equipment",
    "animated visualization", "text-heavy slide", "person talking to camera",
    "handwritten notes", "3d rendered animation", "cartoon for children",
]
# Scenes where real objects exist -> YOLO is meaningful. Everything else
# (animation, diagrams, slides) -> suppress YOLO (saves time, kills hallucinations).
REALWORLD_SCENES = {
    "laboratory experiment", "demonstration with equipment",
    "person talking to camera", "teacher at a whiteboard", "student discussion",
}
# Scenes likely to carry on-screen text -> run OCR; skip OCR elsewhere.
TEXTY_SCENES = {
    "slide presentation", "text-heavy slide", "handwritten notes",
    "diagram explanation",
}


def load_config(overrides: dict | None = None) -> dict:
    """Merge BASE + chosen PROFILE + caller overrides into one flat dict."""
    cfg = dict(BASE)
    if overrides:
        cfg.update(overrides)
    profile = cfg.get("PROFILE", "fast")
    if profile not in PROFILES:
        raise ValueError(f"Unknown PROFILE {profile!r}; choose {list(PROFILES)}")
    cfg["PROFILE"] = profile
    for k, v in PROFILES[profile].items():
        cfg.setdefault(k, v)          # profile fills gaps; explicit overrides win
    cfg["SCENE_LABELS"] = SCENE_LABELS
    cfg["REALWORLD_SCENES"] = REALWORLD_SCENES
    cfg["TEXTY_SCENES"] = TEXTY_SCENES
    return cfg
