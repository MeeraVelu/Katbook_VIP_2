"""
tagging.py — Stage 4. The LLM fuses every signal into strict per-segment JSON
tags (topic / subject / grade / difficulty / tags / summary / ...).

Production upgrades:
  * Two prompts. VOICE = transcript is ground truth, visuals are weak noisy hints.
    SILENT = there is NO transcript, so OCR + captions + scenes ARE the evidence
    and the model is told to infer the subject from them (and lower confidence).
  * Cross-segment CONSISTENCY pass. After tagging, the dominant subject/grade for
    the whole video is computed and outlier segments are reconciled -- this fixes
    the "Chemistry video, segment 2 labelled Mathematics" failure.
  * Robust JSON recovery (fences stripped, truncation repaired, regex fallback).

The tagging LLM now runs behind a pluggable backend (:mod:`llm_backend`): vLLM
over HTTP in production (Qwen2.5-7B FP8), in-process transformers for GPU boxes
without vLLM, or a deterministic stub for the CPU smoke test. The prompts, the
strict JSON schema, the robust recovery, and the cross-segment consistency pass
are UNCHANGED. One malformed output is retried once with a stricter reminder.
"""

from __future__ import annotations

import json
import re
from collections import Counter

import numpy as np

from .llm_backend import get_backend
from .router import SILENT
from .utils import log

_SCHEMA = (
    "Return ONLY valid JSON, no prose, with EXACTLY these keys: "
    '{"topic": str, "subtopics": [str], '
    '"content_type": "lecture|tutorial|demo|discussion|animation|rhyme", '
    '"difficulty": "beginner|intermediate|advanced|expert", '
    '"grade_level": str, "subject": str, "summary": str, "tags": [str], '
    '"speaker_role": "teacher|student|narrator|none", "language": str, '
    '"has_visual_content": bool, "confidence": float, '
    '"bloom_level": "remember|understand|apply|analyze|evaluate|create", '
    '"learning_objectives": [str], "est_min": float, '
    '"knowledge_type": "conceptual|procedural|factual|metacognitive", '
    '"prerequisites": [str]}'
)

_DOMAIN = (
    "Katbook is a multilingual K-12 / college EdTech platform; content is often in "
    "Tamil, Hindi or English. Use a BROAD school taxonomy: Languages (Tamil, English, "
    "Alphabets & Phonics, Vocabulary, Rhymes), Mathematics, Science (Physics / "
    "Chemistry / Biology), Environmental Studies, Social Studies, General Knowledge. "
    "Write topic, subject, summary, subtopics and tags in ENGLISH (never raw transcript "
    "fragments). 'language' = the spoken (or on-screen) language. Pick the grade that "
    "fits the content (an alphabet / rhyme / simple animation for young children is "
    "Kindergarten or Grade 1-2). The 'topic' must be the SPECIFIC lesson focus "
    "(e.g. 'Balancing Chemical Equations', 'Tamil vowel letters'), never just the "
    "bare subject name like 'Chemistry' or 'Languages'. 'bloom_level' = the single "
    "dominant cognitive level (Bloom's taxonomy) this segment targets — 'remember' "
    "(recall facts) through 'create' (original synthesis); most lecture segments are "
    "'remember' or 'understand'. 'learning_objectives' = 1-3 short ENGLISH statements "
    "of the form 'Students will be able to ...', specific to THIS segment's content. "
    "'est_min' = realistic minutes for a student to watch and absorb this segment "
    "(usually close to its actual duration; higher for dense/complex content). "
    "'knowledge_type' = classify what KIND of knowledge this segment teaches: "
    "'conceptual' explains ideas/theories, 'what is X' (e.g. 'what is photosynthesis'); "
    "'procedural' teaches steps or methods, 'how to do X' (e.g. 'how to balance an "
    "equation'); 'factual' presents specific facts, formulas, or data (e.g. 'the speed "
    "of light is 3x10^8 m/s'); 'metacognitive' teaches learning strategies, 'how to "
    "learn X' (e.g. study techniques). 'prerequisites' = list 1-3 short pieces of "
    "prior knowledge a student needs BEFORE watching this segment (e.g. "
    "['basic algebra', 'understanding of atoms']); return [] if none needed."
)


def _voice_prompt(seg: dict, language: str) -> str:
    return (
        f"{_DOMAIN}\n\n"
        f"Detected spoken language: {language}\n\n"
        f"TRANSCRIPT (this is the GROUND TRUTH of what is taught — base tags on THIS):\n"
        f'"""{seg["text"][:3000]}"""\n\n'
        f"On-screen text (OCR, may confirm the topic): {seg.get('ocr', '')[:300]}\n"
        f"Weak visual hints (auto-detected, OFTEN WRONG — never make these the subject): "
        f"scenes={seg.get('scenes', [])}, objects={seg.get('objects', [])}\n\n{_SCHEMA}"
    )


def _silent_prompt(seg: dict, language: str) -> str:
    return (
        f"{_DOMAIN}\n\n"
        f"IMPORTANT: This video segment has NO narration / no speech. There is no "
        f"transcript. Infer the educational topic from the VISUAL EVIDENCE below. "
        f"Be reasonable but set a LOWER confidence (<= 0.6) because there is no audio.\n\n"
        f"On-screen text (OCR — strongest available signal): {seg.get('ocr', '')[:400]}\n"
        f"Frame captions (what the visuals depict): {seg.get('captions', [])}\n"
        f"Scene labels: {seg.get('scenes', [])}\n"
        f"Detected objects (only present for real-world footage): {seg.get('objects', [])}\n"
        f"On-screen language hint: {language}\n\n{_SCHEMA}"
    )


def _parse_llm(raw: str) -> dict:
    t = (raw or "").strip()
    t = re.sub(r"^```(?:json)?", "", t).strip()
    t = re.sub(r"```$", "", t).strip()
    m = re.search(r"\{.*", t, re.DOTALL)
    if not m:
        return {"_parse_error": raw[:300]}
    js = m.group(0)
    for cand in (js, js + "}", js + '"}', js + '"}}', js[: js.rfind("}") + 1] if "}" in js else js):
        try:
            return json.loads(cand)
        except Exception:
            pass

    # ---- field-by-field regex fallback for TRUNCATED output ----
    # Recover every field the truncated JSON completed, including the list and
    # numeric fields the old fallback dropped (subtopics, confidence) — those
    # were the keys that came back empty/None whenever a segment hit this path.
    def grab_str(k):
        mm = re.search(rf'"{k}"\s*:\s*"([^"]*)"', js)
        return mm.group(1) if mm else None

    def grab_list(k):
        mm = re.search(rf'"{k}"\s*:\s*\[(.*?)\]', js, re.DOTALL)
        if not mm:
            return None
        return [x.strip().strip('"') for x in mm.group(1).split(",") if x.strip().strip('"')]

    def grab_num(k):
        mm = re.search(rf'"{k}"\s*:\s*([0-9]*\.?[0-9]+)', js)
        return float(mm.group(1)) if mm else None

    def grab_bool(k):
        mm = re.search(rf'"{k}"\s*:\s*(true|false)', js)
        return (mm.group(1) == "true") if mm else None

    out = {
        "topic": grab_str("topic"),
        "subject": grab_str("subject"),
        "grade_level": grab_str("grade_level"),
        "difficulty": grab_str("difficulty"),
        "content_type": grab_str("content_type"),
        "summary": grab_str("summary"),
        "speaker_role": grab_str("speaker_role"),
        "language": grab_str("language"),
        "tags": grab_list("tags"),
        "subtopics": grab_list("subtopics"),
        "confidence": grab_num("confidence"),
        "has_visual_content": grab_bool("has_visual_content"),
        "bloom_level": grab_str("bloom_level"),
        "learning_objectives": grab_list("learning_objectives"),
        "est_min": grab_num("est_min"),
        "knowledge_type": grab_str("knowledge_type"),
        "prerequisites": grab_list("prerequisites"),
        "_recovered": True,  # flag: this came from truncation recovery, not strict parse
    }
    out = {k: v for k, v in out.items() if v is not None}
    # if literally nothing recovered (not even a topic), surface the raw error
    return out if out.get("topic") or out.get("summary") else {"_parse_error": raw[:300]}


def _finalize_fields(d: dict, is_silent: bool) -> dict:
    """Guarantee the keys downstream code (and the JSON) expect always exist with
    sensible defaults, so a parse/recovery never yields null confidence or a
    missing subtopics list. Defaults are conservative; recovery is flagged."""
    if "_parse_error" in d:
        return d
    d.setdefault("subtopics", [])
    d.setdefault("tags", [])
    # confidence: never leave it null. If the model omitted it (common on the
    # recovery path), default by route — silent inference is inherently less sure.
    if d.get("confidence") is None:
        d["confidence"] = 0.5 if is_silent else 0.7
        d["confidence_defaulted"] = True
    else:
        try:
            d["confidence"] = round(float(d["confidence"]), 2)
        except Exception:
            d["confidence"] = 0.5 if is_silent else 0.7
            d["confidence_defaulted"] = True
    # silent path must never claim high confidence
    if is_silent and d["confidence"] > 0.6:
        d["confidence"] = 0.6
    return d


def _dominant_value(segments: list[dict], field: str):
    """Video-level value for a per-segment field: the most common one, with ties
    broken by the HIGHEST-CONFIDENCE segment (so a 1-1 split still resolves)."""
    vals = [
        (s.get("llm", {}).get(field), float(s.get("llm", {}).get("confidence") or 0))
        for s in segments
        if s.get("llm", {}).get(field)
    ]
    if not vals:
        return None
    counts = Counter(v for v, _ in vals)
    top, n = counts.most_common(1)[0]
    if list(counts.values()).count(n) > 1:  # tie -> highest-confidence segment wins
        top = max(vals, key=lambda x: x[1])[0]
    return top


def _consistency_pass(segments: list[dict]) -> None:
    """Unify subject + grade across ALL segments of ONE video.

    A single coherent video should carry one subject and one grade — but the LLM
    tags each segment independently and can disagree (e.g. seg1 'Chemistry/Grade
    9-10', seg2 'Mathematics/Grade 7-8'). We always reconcile to the video-level
    dominant value (ties broken by confidence) and apply it to every segment,
    keeping the original under *_raw. Per-segment topic/subtopics/tags stay distinct
    so fine-grained access still works.
    """
    dom_subject = _dominant_value(segments, "subject")
    dom_grade = _dominant_value(segments, "grade_level")
    for s in segments:
        llm = s.get("llm", {})
        if dom_subject and llm.get("subject") and llm["subject"] != dom_subject:
            llm["subject_raw"] = llm["subject"]
            llm["subject"] = dom_subject
        if dom_grade and llm.get("grade_level") and llm["grade_level"] != dom_grade:
            llm.setdefault("grade_level_raw", llm["grade_level"])
            llm["grade_level"] = dom_grade


_SYSTEM = "You are a precise educational video tagging engine."
_RETRY_HINT = (
    "\n\nYour previous answer was not valid JSON. Reply with ONLY the "
    "JSON object, no prose, no markdown fences, all keys present."
)


def tag_segments(payload: dict, route_path: str, cfg: dict, device: str) -> None:
    """Tag every segment in place (payload['segments'][i]['llm']).

    The model is opened ONCE (loaded for `inprocess`, a client for `vllm`), used
    for every segment, then released -- preserving the one-model-at-a-time VRAM
    discipline. A malformed output is retried once with a stricter reminder."""
    language = payload.get("language") or "unknown"
    is_silent = route_path == SILENT
    max_new = cfg["LLM_MAX_NEW_TOKENS"]

    with get_backend(cfg, device) as backend:
        for i, seg in enumerate(payload["segments"]):
            prompt = _silent_prompt(seg, language) if is_silent else _voice_prompt(seg, language)
            raw = backend.generate(_SYSTEM, prompt, max_new)
            parsed = _finalize_fields(_parse_llm(raw), is_silent)
            if "_parse_error" in parsed:  # one retry with a stricter instruction
                raw2 = backend.generate(_SYSTEM, prompt + _RETRY_HINT, max_new)
                retry = _finalize_fields(_parse_llm(raw2), is_silent)
                if "_parse_error" not in retry:
                    parsed = retry
                    parsed["_retried"] = True
            seg["llm"] = parsed
            log(
                f"seg {i}: topic={seg['llm'].get('topic')!r} "
                f"subject={seg['llm'].get('subject')!r} "
                f"conf={seg['llm'].get('confidence')}"
                f"{' [recovered]' if seg['llm'].get('_recovered') else ''}"
            )

    _consistency_pass(payload["segments"])


def embed_segments(payload: dict, embedder) -> np.ndarray:
    """Embed each segment (LLM summary, or transcript/OCR fallback) for search.

    The empty-case width comes from the embedder itself (BGE-M3 = 1024-d in
    production, MiniLM = 384-d on the T4/smoke profiles), so a video that yields
    zero segments still returns a correctly-shaped array for the vector column."""
    texts = []
    for s in payload["segments"]:
        llm = s.get("llm", {})
        texts.append(
            llm.get("summary")
            or s.get("text")
            or s.get("ocr")
            or (s.get("captions") or [""])[0]
            or "untitled segment"
        )
    if not texts:
        dim = getattr(embedder, "get_sentence_embedding_dimension", lambda: 384)() or 384
        return np.zeros((0, int(dim)))
    return embedder.encode(texts, normalize_embeddings=True)
