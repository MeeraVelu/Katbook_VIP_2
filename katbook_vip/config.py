"""
config.py — public configuration surface for the pipeline.

Historically this module *was* the config (a hand-rolled ``BASE`` dict + profile
dicts). It is now a thin compatibility shim over :mod:`katbook_vip.settings`
(pydantic-settings), so:

* every existing env var name (``KVIP_*``, ``DATABASE_URL``, ...) keeps working;
* ``load_config(overrides)`` still returns the same flat ``dict`` the pipeline
  modules consume (``cfg["WHISPER_MODEL"]`` etc.);
* the scene vocabulary that gates YOLO/OCR lives here, unchanged.

Importing this module is free (no torch, no GPU).
"""

from __future__ import annotations

from typing import Any

from .settings import PROFILES, get_settings

__all__ = ["load_config", "PROFILES", "SCENE_LABELS", "REALWORLD_SCENES", "TEXTY_SCENES"]


# CLIP zero-shot scene vocabulary. The "real-world vs synthetic" split below
# decides whether YOLO runs (it hallucinates on animation/diagrams) and whether
# OCR runs (text-heavy frames only). Tune to your content.
SCENE_LABELS = [
    "teacher at a whiteboard",
    "slide presentation",
    "laboratory experiment",
    "student discussion",
    "diagram explanation",
    "demonstration with equipment",
    "animated visualization",
    "text-heavy slide",
    "person talking to camera",
    "handwritten notes",
    "3d rendered animation",
    "cartoon for children",
    "letter or word flashcard",
    "cooking or kitchen demonstration",
    "live-action people indoors",
    "nature or animal illustration",
]
# Scenes where real objects exist -> YOLO is meaningful. Everything else
# (animation, diagrams, slides, flashcards) -> suppress YOLO (saves time, kills
# hallucinations).
REALWORLD_SCENES = {
    "laboratory experiment",
    "demonstration with equipment",
    "person talking to camera",
    "teacher at a whiteboard",
    "student discussion",
    "cooking or kitchen demonstration",
    "live-action people indoors",
}
# Scenes likely to carry on-screen text -> run OCR; skip OCR elsewhere.
TEXTY_SCENES = {
    "slide presentation",
    "text-heavy slide",
    "handwritten notes",
    "diagram explanation",
    "letter or word flashcard",
}


def load_config(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """Merge Settings(env) + chosen PROFILE + caller overrides into one flat dict.

    Precedence (highest wins): caller ``overrides`` -> explicit env overrides
    (e.g. ``KVIP_EMBED_MODEL``) -> PROFILE defaults.
    """
    settings = get_settings()
    cfg = settings.as_config()
    if overrides:
        cfg.update(overrides)

    profile = cfg.get("PROFILE", "fast")
    if profile not in PROFILES:
        raise ValueError(f"Unknown PROFILE {profile!r}; choose {list(PROFILES)}")
    cfg["PROFILE"] = profile
    # profile fills any gap the env/overrides did not already set
    for k, v in PROFILES[profile].items():
        cfg.setdefault(k, v)

    cfg["SCENE_LABELS"] = SCENE_LABELS
    cfg["REALWORLD_SCENES"] = REALWORLD_SCENES
    cfg["TEXTY_SCENES"] = TEXTY_SCENES
    return cfg
