"""
audio.py — Stage 2A. Detect whether the video actually contains narration,
then (only if it does) transcribe it and compute audio features.

The speech-presence gate is what makes the "works with and without voice" promise
real: a silent/music-only clip is detected here (mean RMS below a dB floor and/or
no Whisper VAD speech), so the router sends it down the visual-first path instead
of feeding Whisper silence and getting hallucinated tags.

Whisper is loaded lazily and freed immediately after use (one model at a time).
Whisper auto-detects the spoken language, so ANY language is transcribed; tags are
later forced to English by the LLM prompt.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from .utils import free_vram, log, managed_model


# --------------------------------------------------------------------------- #
# Speech-presence detection — cheap, via ffmpeg RMS. No librosa needed for the
# gate (faster). Validated: silent clip ~ -99 dB, narration ~ -20..-30 dB.
# --------------------------------------------------------------------------- #
def mean_rms_db(wav_path: Path) -> float:
    cp = subprocess.run(
        [
            "ffmpeg",
            "-i",
            str(wav_path),
            "-af",
            "astats=metadata=1:reset=0,ametadata=mode=print:key=lavfi.astats.Overall.RMS_level",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
    )
    vals = [
        float(line.split("=")[-1])
        for line in cp.stderr.splitlines()
        if "RMS_level" in line and "=" in line and "inf" not in line.split("=")[-1].lower()
    ]
    return sum(vals) / len(vals) if vals else -99.0


def detect_speech(wav_path: Path, silence_db: float) -> tuple[bool, float]:
    """Returns (likely_has_speech, mean_rms_db). Cheap pre-check before Whisper."""
    if not wav_path.exists():
        return False, -99.0
    rms = mean_rms_db(wav_path)
    return (rms > silence_db), round(rms, 1)


# --------------------------------------------------------------------------- #
# Transcription (faster-whisper). Adaptive compute type so the stage never dies
# if a Kaggle/CTranslate2 build rejects float16.
# --------------------------------------------------------------------------- #
def _load_whisper(model_name: str, device: str):
    from faster_whisper import WhisperModel

    attempts = [
        (device, "float16"),
        (device, "int8_float16" if device == "cuda" else "int8"),
        ("cpu", "int8"),
    ]
    last, seen = None, set()
    for dev, ct in attempts:
        if (dev, ct) in seen:
            continue
        seen.add((dev, ct))
        try:
            m = WhisperModel(model_name, device=dev, compute_type=ct)
            log(f"whisper: device={dev} compute_type={ct}")
            return m
        except Exception as e:
            last = e
            log(f"whisper {dev}/{ct} unavailable ({str(e)[:60]}); next", "WARN")
    raise last


def transcribe(wav_path: Path, *, model_name: str, device: str, beam_size: int = 1) -> dict:
    """
    Returns {"transcript":[{start,end,text}], "language", "language_prob",
             "full_text", "speech_sec"}. Empty transcript if no speech found.
    beam_size=1 + condition_on_previous_text=False = fastest, fine for tagging.
    """
    with managed_model("Whisper") as keep:
        whisper = keep(_load_whisper(model_name, device))
        seg_iter, info = whisper.transcribe(
            str(wav_path),
            beam_size=beam_size,
            vad_filter=True,
            condition_on_previous_text=False,
            word_timestamps=False,
        )
        transcript = [
            {"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()}
            for s in seg_iter
        ]

    full_text = " ".join(s["text"] for s in transcript).strip()
    speech_sec = sum(s["end"] - s["start"] for s in transcript)
    log(
        f"whisper: lang={info.language} ({info.language_probability:.2f}) "
        f"segments={len(transcript)} speech={speech_sec:.0f}s"
    )
    return {
        "transcript": transcript,
        "language": info.language,
        "language_prob": round(float(info.language_probability), 3),
        "full_text": full_text,
        "speech_sec": round(speech_sec, 1),
    }


def audio_features(wav_path: Path, duration: float, full_text: str) -> dict:
    """RMS energy / silence ratio / words-per-minute. librosa optional."""
    try:
        import librosa
        import numpy as np

        y, _ = librosa.load(str(wav_path), sr=16000)
        intervals = librosa.effects.split(y, top_db=30)
        voiced = sum((e - s) for s, e in intervals) / 16000 if len(intervals) else 0
        rms = float(np.mean(librosa.feature.rms(y=y)))
        feats = {
            "rms_energy": round(rms, 4),
            "silence_ratio": round(1 - voiced / max(duration, 1e-6), 3),
            "words_per_minute": round(len(full_text.split()) / max(duration / 60, 1e-6), 1),
        }
        free_vram(y)
        return feats
    except Exception as e:  # librosa missing/slow -> fall back to RMS-only
        return {
            "rms_energy": None,
            "silence_ratio": None,
            "words_per_minute": round(len(full_text.split()) / max(duration / 60, 1e-6), 1),
            "_note": f"librosa unavailable ({str(e)[:40]})",
        }
