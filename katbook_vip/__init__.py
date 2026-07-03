"""
Katbook VIP — Video Intelligence Platform pipeline.

Turns lecture/animation videos into per-segment structured tags (topic, subject,
grade, difficulty, tags, summary + embeddings), stored in Postgres and queryable
by meaning or keyword. Runs on a free Kaggle T4, one model in VRAM at a time, and
handles BOTH narrated and silent videos in ANY language.

    from katbook_vip import run_batch, load_config
    run_batch(load_config({"PROCESS": "all", "PROFILE": "fast"}))
"""

from .config import PROFILES, load_config  # noqa: F401
from .pipeline import process_one_video  # noqa: F401
from .run import discover_videos, run_batch, select_videos  # noqa: F401
from .settings import Settings, get_settings  # noqa: F401

__version__ = "3.0.0"
__all__ = [
    "load_config",
    "PROFILES",
    "Settings",
    "get_settings",
    "run_batch",
    "discover_videos",
    "select_videos",
    "process_one_video",
    "__version__",
]
