"""
router.py — the small "brain" that decides how each video is processed so that
both narrated and silent videos produce good tags.

Decision (made once, early, from cheap signals):
  * has_speech == False (silent / music-only)  -> SILENT path
  * spoken seconds below MIN_SPEECH_SEC         -> SILENT path
  * otherwise                                   -> VOICE path

The chosen path then drives:
  * frame density   (silent needs more frames; voiced needs few)
  * OCR coverage    (silent OCRs every frame)
  * captioning      (silent forces BLIP-2 on)
  * segmentation    (voiced = transcript cosine; silent = scene grouping)
  * the LLM prompt  (transcript-primary vs visual-primary)
"""

from __future__ import annotations

from dataclasses import dataclass

VOICE = "voice"
SILENT = "silent"


@dataclass
class RoutePlan:
    path: str  # VOICE | SILENT
    has_speech: bool
    mean_rms_db: float
    max_frames: int
    ocr_all_frames: bool
    force_captions: bool
    reason: str


def decide(*, has_speech: bool, mean_rms_db: float, speech_sec: float, cfg: dict) -> RoutePlan:
    silent = (not has_speech) or (speech_sec < cfg["MIN_SPEECH_SEC"])
    if silent:
        return RoutePlan(
            path=SILENT,
            has_speech=has_speech,
            mean_rms_db=mean_rms_db,
            max_frames=cfg["MAX_FRAMES_SILENT"],
            ocr_all_frames=True,
            force_captions=True,
            reason=(
                f"no narration (rms={mean_rms_db}dB, speech={speech_sec}s) -> visual-first tagging"
            ),
        )
    return RoutePlan(
        path=VOICE,
        has_speech=True,
        mean_rms_db=mean_rms_db,
        max_frames=cfg["MAX_FRAMES_VOICE"],
        ocr_all_frames=False,
        force_captions=False,
        reason=f"narration present (speech={speech_sec}s) -> transcript-first tagging",
    )
