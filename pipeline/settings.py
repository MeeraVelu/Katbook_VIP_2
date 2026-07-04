"""
settings.py — typed configuration for the Katbook VIP pipeline (pydantic-settings).

This replaces the old hand-rolled ``os.environ.get`` dict with a validated
``Settings`` model, **layered over the exact same environment variable names** the
POC used (``KVIP_*``, ``DATABASE_URL``, ``HF_TOKEN``, ...), so nothing that already
set those env vars breaks.

The rest of the pipeline still consumes a flat ``dict`` (``cfg["WHISPER_MODEL"]``),
so ``config.load_config()`` calls ``Settings().as_config()`` and merges the chosen
speed PROFILE on top — the public contract of ``load_config`` is unchanged.

Nothing here imports torch or loads a model; importing this module is free.
"""

from __future__ import annotations

from typing import Any

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# --------------------------------------------------------------------------- #
# Speed profiles. Each flips every model/sampling knob together.
#   fast/balanced/quality  — as in the POC (T4-class).
#   production             — RTX 5090 (Blackwell, 32 GB): large models, FP16/FP8.
#   smoke                  — tiny CPU models for the GPU-free end-to-end smoke test.
# --------------------------------------------------------------------------- #
PROFILES: dict[str, dict[str, Any]] = {
    "fast": {
        "WHISPER_MODEL": "medium",
        "CLIP_MODEL": "openai/clip-vit-base-patch32",
        "YOLO_MODEL": "yolov8n.pt",
        "BLIP2_MODEL": "Salesforce/blip2-opt-2.7b",
        "LLM_MODEL": "Qwen/Qwen2.5-7B-Instruct",
        "EMBED_MODEL": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        "EMBED_DIM": 384,
        "TAGGING_BACKEND": "inprocess",
        "MAX_FRAMES_VOICE": 12,
        "MAX_FRAMES_SILENT": 24,
        "CAPTION_FRAMES": 6,
        "USE_SCENE_CUTS": True,
        "WHISPER_BEAM": 1,
        "RESIDENT_VISUAL_STACK": False,
    },
    "balanced": {
        "WHISPER_MODEL": "medium",
        "CLIP_MODEL": "openai/clip-vit-base-patch32",
        "YOLO_MODEL": "yolov8s.pt",
        "BLIP2_MODEL": "Salesforce/blip2-opt-2.7b",
        "LLM_MODEL": "Qwen/Qwen2.5-7B-Instruct",
        "EMBED_MODEL": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        "EMBED_DIM": 384,
        "TAGGING_BACKEND": "inprocess",
        "MAX_FRAMES_VOICE": 18,
        "MAX_FRAMES_SILENT": 32,
        "CAPTION_FRAMES": 10,
        "USE_SCENE_CUTS": True,
        "WHISPER_BEAM": 3,
        "RESIDENT_VISUAL_STACK": False,
    },
    "quality": {
        "WHISPER_MODEL": "large-v3",
        "CLIP_MODEL": "openai/clip-vit-large-patch14",
        "YOLO_MODEL": "yolov8m.pt",
        "BLIP2_MODEL": "Salesforce/blip2-opt-2.7b",
        "LLM_MODEL": "Qwen/Qwen2.5-7B-Instruct",
        "EMBED_MODEL": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        "EMBED_DIM": 384,
        "TAGGING_BACKEND": "inprocess",
        "MAX_FRAMES_VOICE": 30,
        "MAX_FRAMES_SILENT": 48,
        "CAPTION_FRAMES": 16,
        "USE_SCENE_CUTS": True,
        "WHISPER_BEAM": 5,
        "RESIDENT_VISUAL_STACK": False,
    },
    # ----- RTX 5090 production defaults (approved POC->Production comparison) ---- #
    "production": {
        "WHISPER_MODEL": "large-v3",  # FP16 via faster-whisper (CTranslate2)
        "WHISPER_COMPUTE_TYPE": "float16",
        "CLIP_MODEL": "openai/clip-vit-large-patch14",
        "YOLO_MODEL": "yolo11x.pt",  # ultralytics YOLO11x, still gated
        "BLIP2_MODEL": "Salesforce/blip2-opt-2.7b",  # FP16; opt-6.7b via KVIP_BLIP2_MODEL
        "BLIP2_DTYPE": "float16",
        "LLM_MODEL": "Qwen/Qwen2.5-7B-Instruct",  # served by vLLM (FP8); 14B = config swap
        "EMBED_MODEL": "BAAI/bge-m3",  # 1024-d, strong Tamil/Hindi/English
        "EMBED_DIM": 1024,
        "TAGGING_BACKEND": "vllm",
        "MAX_FRAMES_VOICE": 18,
        "MAX_FRAMES_SILENT": 40,
        "CAPTION_FRAMES": 12,
        "USE_SCENE_CUTS": True,
        "WHISPER_BEAM": 3,
        "RESIDENT_VISUAL_STACK": True,  # 32 GB: keep CLIP+YOLO+OCR resident
    },
    # ----- CPU smoke test: smallest everything, no GPU, no big downloads -------- #
    "smoke": {
        "WHISPER_MODEL": "tiny",
        "WHISPER_COMPUTE_TYPE": "int8",
        "CLIP_MODEL": "openai/clip-vit-base-patch32",
        "YOLO_MODEL": "yolov8n.pt",
        "BLIP2_MODEL": "Salesforce/blip2-opt-2.7b",
        "BLIP2_DTYPE": "float32",
        "LLM_MODEL": "Qwen/Qwen2.5-0.5B-Instruct",
        "EMBED_MODEL": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        "EMBED_DIM": 384,
        "TAGGING_BACKEND": "stub",  # deterministic, no model download
        "MAX_FRAMES_VOICE": 4,
        "MAX_FRAMES_SILENT": 6,
        "CAPTION_FRAMES": 0,
        "USE_SCENE_CUTS": False,
        "WHISPER_BEAM": 1,
        "RESIDENT_VISUAL_STACK": False,
    },
}

# Known embedder output dimensions — used to fail fast on an EMBED_DIM mismatch
# (a 384-d model written into a vector(1024) column corrupts search silently).
KNOWN_EMBED_DIMS: dict[str, int] = {
    "BAAI/bge-m3": 1024,
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2": 384,
    "sentence-transformers/all-MiniLM-L6-v2": 384,
}


class Settings(BaseSettings):
    """Environment-driven settings. Field names are lowercase; each declares the
    exact legacy env var via ``validation_alias`` so old env names keep working."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )

    # --- input / selection --------------------------------------------------- #
    video_glob: str = Field(
        "/kaggle/input/**/*.mp4", validation_alias=AliasChoices("KVIP_VIDEO_GLOB", "video_glob")
    )
    video_exts: str = Field(
        "mp4,webm,mov,mkv,avi,m4v", validation_alias=AliasChoices("KVIP_VIDEO_EXTS", "video_exts")
    )
    process: str = Field("all", validation_alias=AliasChoices("KVIP_PROCESS", "process"))
    skip_existing: bool = Field(
        True, validation_alias=AliasChoices("KVIP_SKIP_EXISTING", "skip_existing")
    )
    dedup_by_hash: bool = Field(
        True, validation_alias=AliasChoices("KVIP_DEDUP_BY_HASH", "dedup_by_hash")
    )

    # --- output -------------------------------------------------------------- #
    work_dir: str = Field("/data/work", validation_alias=AliasChoices("KVIP_WORK_DIR", "work_dir"))

    # --- profile ------------------------------------------------------------- #
    profile: str = Field("fast", validation_alias=AliasChoices("KVIP_PROFILE", "profile"))

    # --- OCR / routing ------------------------------------------------------- #
    # None = not explicitly set → the tier/profile decides (final fallback "en").
    ocr_langs: str | None = Field(
        None, validation_alias=AliasChoices("KVIP_OCR_LANGS", "ocr_langs")
    )
    silence_db: float = Field(-50.0, validation_alias=AliasChoices("KVIP_SILENCE_DB", "silence_db"))
    min_speech_sec: float = Field(
        3.0, validation_alias=AliasChoices("KVIP_MIN_SPEECH_SEC", "min_speech_sec")
    )
    run_audio_features: bool = Field(
        False, validation_alias=AliasChoices("KVIP_AUDIO_FEATURES", "run_audio_features")
    )

    # --- segmentation -------------------------------------------------------- #
    max_segment_sec: float = Field(
        120.0, validation_alias=AliasChoices("KVIP_MAX_SEGMENT_SEC", "max_segment_sec")
    )

    # --- storage ------------------------------------------------------------- #
    database_url: str | None = Field(
        None, validation_alias=AliasChoices("DATABASE_URL", "database_url")
    )
    enable_db: bool = Field(True, validation_alias=AliasChoices("KVIP_ENABLE_DB", "enable_db"))

    # --- LLM tagging --------------------------------------------------------- #
    llm_max_new_tokens: int = Field(
        512, validation_alias=AliasChoices("KVIP_LLM_TOKENS", "llm_max_new_tokens")
    )
    tagging_backend: str | None = Field(
        None, validation_alias=AliasChoices("KVIP_TAGGING_BACKEND", "tagging_backend")
    )
    vllm_base_url: str = Field(
        "http://vllm:8000/v1", validation_alias=AliasChoices("VLLM_BASE_URL", "vllm_base_url")
    )
    vllm_model: str = Field(
        "Qwen/Qwen2.5-7B-Instruct", validation_alias=AliasChoices("VLLM_MODEL", "vllm_model")
    )
    vllm_api_key: str = Field(
        "EMPTY", validation_alias=AliasChoices("VLLM_API_KEY", "vllm_api_key")
    )

    # --- optional per-knob overrides (win over the profile) ------------------ #
    embed_model: str | None = Field(
        None, validation_alias=AliasChoices("KVIP_EMBED_MODEL", "embed_model")
    )
    embed_dim: int | None = Field(
        None, validation_alias=AliasChoices("KVIP_EMBED_DIM", "embed_dim")
    )
    blip2_model: str | None = Field(
        None, validation_alias=AliasChoices("KVIP_BLIP2_MODEL", "blip2_model")
    )
    whisper_model: str | None = Field(
        None, validation_alias=AliasChoices("KVIP_WHISPER_MODEL", "whisper_model")
    )
    resident_visual_stack: bool | None = Field(
        None, validation_alias=AliasChoices("KVIP_RESIDENT_VISUAL_STACK", "resident_visual_stack")
    )

    # --- media --------------------------------------------------------------- #
    ffmpeg_hwaccel: str = Field(
        "auto", validation_alias=AliasChoices("KVIP_FFMPEG_HWACCEL", "ffmpeg_hwaccel")
    )

    # --- misc ---------------------------------------------------------------- #
    hf_token: str | None = Field(None, validation_alias=AliasChoices("HF_TOKEN", "hf_token"))

    @field_validator("profile")
    @classmethod
    def _known_profile(cls, v: str) -> str:
        if v not in PROFILES:
            raise ValueError(f"Unknown PROFILE {v!r}; choose {list(PROFILES)}")
        return v

    @model_validator(mode="after")
    def _validate_embed_dim(self) -> Settings:
        """Fail fast when an explicit EMBED_MODEL and EMBED_DIM disagree, or when
        an explicit EMBED_DIM contradicts a known model's true dimension."""
        model = self.embed_model or PROFILES[self.profile].get("EMBED_MODEL")
        known = KNOWN_EMBED_DIMS.get(model or "")
        if self.embed_dim is not None and known is not None and self.embed_dim != known:
            raise ValueError(
                f"EMBED_DIM={self.embed_dim} contradicts embedder {model!r} "
                f"(true dimension {known}). Fix KVIP_EMBED_DIM or KVIP_EMBED_MODEL."
            )
        return self

    def as_config(self) -> dict[str, Any]:
        """Flatten into the plain dict the pipeline consumes (BASE keys only;
        ``config.load_config`` merges the PROFILE knobs and scene vocab on top)."""
        exts = [e.strip().lower().lstrip(".") for e in self.video_exts.split(",") if e.strip()]
        cfg: dict[str, Any] = {
            "VIDEO_GLOB": self.video_glob,
            "VIDEO_EXTS": exts,
            "PROCESS": self.process,
            "SKIP_EXISTING": self.skip_existing,
            "DEDUP_BY_HASH": self.dedup_by_hash,
            "WORK_DIR": self.work_dir,
            "RESULTS_SUBDIR": "results",
            "CHECKPOINT_SUBDIR": "checkpoints",
            "PROFILE": self.profile,
            "SILENCE_DB": self.silence_db,
            "MIN_SPEECH_SEC": self.min_speech_sec,
            "RUN_AUDIO_FEATURES": self.run_audio_features,
            "WINDOW_SEC": 30,
            "MIN_SEGMENT_SEC": 45,
            "MAX_SEGMENT_SEC": self.max_segment_sec,
            "MAX_SEGMENTS": 12,
            "SIM_DROP_FALLBACK": 0.25,
            "DATABASE_URL": self.database_url,
            "ENABLE_DB": self.enable_db,
            "LLM_MAX_NEW_TOKENS": self.llm_max_new_tokens,
            "VLLM_BASE_URL": self.vllm_base_url,
            "VLLM_MODEL": self.vllm_model,
            "VLLM_API_KEY": self.vllm_api_key,
            "FFMPEG_HWACCEL": self.ffmpeg_hwaccel,
            "HF_TOKEN": self.hf_token,
        }
        # optional explicit overrides (win over the profile in load_config)
        ocr = (
            [x.strip() for x in self.ocr_langs.split(",") if x.strip()]
            if self.ocr_langs is not None
            else None
        )
        for key, val in (
            ("EMBED_MODEL", self.embed_model),
            ("EMBED_DIM", self.embed_dim),
            ("BLIP2_MODEL", self.blip2_model),
            ("WHISPER_MODEL", self.whisper_model),
            ("TAGGING_BACKEND", self.tagging_backend),
            ("RESIDENT_VISUAL_STACK", self.resident_visual_stack),
            ("OCR_LANGS", ocr),
        ):
            if val is not None:
                cfg[key] = val
        return cfg


def get_settings(**overrides: Any) -> Settings:
    """Construct Settings from the environment, with optional keyword overrides
    (used by tests to avoid mutating the real environment)."""
    return Settings(**overrides)
