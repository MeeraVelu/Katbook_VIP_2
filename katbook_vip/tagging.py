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

Qwen2.5-7B is loaded in 4-bit ONCE per video, tags all that video's segments,
then is freed -- one heavy model in VRAM at a time.
"""
from __future__ import annotations
import json
import re
from collections import Counter

import numpy as np

from .utils import managed_model, log
from .router import SILENT

_SCHEMA = (
    'Return ONLY valid JSON, no prose, with EXACTLY these keys: '
    '{"topic": str, "subtopics": [str], '
    '"content_type": "lecture|tutorial|demo|discussion|animation|rhyme", '
    '"difficulty": "beginner|intermediate|advanced|expert", '
    '"grade_level": str, "subject": str, "summary": str, "tags": [str], '
    '"speaker_role": "teacher|student|narrator|none", "language": str, '
    '"has_visual_content": bool, "confidence": float}')

_DOMAIN = (
    "Katbook is a multilingual K-12 / college EdTech platform; content is often in "
    "Tamil, Hindi or English. Use a BROAD school taxonomy: Languages (Tamil, English, "
    "Alphabets & Phonics, Vocabulary, Rhymes), Mathematics, Science (Physics / "
    "Chemistry / Biology), Environmental Studies, Social Studies, General Knowledge. "
    "Write topic, subject, summary, subtopics and tags in ENGLISH (never raw transcript "
    "fragments). 'language' = the spoken (or on-screen) language. Pick the grade that "
    "fits the content (an alphabet / rhyme / simple animation for young children is "
    "Kindergarten or Grade 1-2).")


def _voice_prompt(seg: dict, language: str) -> str:
    return (
        f"{_DOMAIN}\n\n"
        f"Detected spoken language: {language}\n\n"
        f"TRANSCRIPT (this is the GROUND TRUTH of what is taught — base tags on THIS):\n"
        f'"""{seg["text"][:3000]}"""\n\n'
        f"On-screen text (OCR, may confirm the topic): {seg.get('ocr', '')[:300]}\n"
        f"Weak visual hints (auto-detected, OFTEN WRONG — never make these the subject): "
        f"scenes={seg.get('scenes', [])}, objects={seg.get('objects', [])}\n\n{_SCHEMA}")


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
        f"On-screen language hint: {language}\n\n{_SCHEMA}")


def _parse_llm(raw: str) -> dict:
    t = (raw or "").strip()
    t = re.sub(r"^```(?:json)?", "", t).strip()
    t = re.sub(r"```$", "", t).strip()
    m = re.search(r"\{.*", t, re.DOTALL)
    if not m:
        return {"_parse_error": raw[:300]}
    js = m.group(0)
    for cand in (js, js + "}", js + '"}', js + '"}}',
                 js[:js.rfind("}") + 1] if "}" in js else js):
        try:
            return json.loads(cand)
        except Exception:
            pass
    # field-by-field regex fallback for truncated output
    def grab(k):
        mm = re.search(rf'"{k}"\s*:\s*"([^"]*)"', js)
        return mm.group(1) if mm else None
    tg = re.search(r'"tags"\s*:\s*\[(.*?)\]', js, re.DOTALL)
    out = {"topic": grab("topic"), "subject": grab("subject"),
           "grade_level": grab("grade_level"), "difficulty": grab("difficulty"),
           "content_type": grab("content_type"), "summary": grab("summary"),
           "tags": [x.strip().strip('"') for x in tg.group(1).split(",") if x.strip()]
           if tg else []}
    out = {k: v for k, v in out.items() if v}
    return out or {"_parse_error": raw[:300]}


def _dominant_value(segments: list[dict], field: str):
    """Video-level value for a per-segment field: the most common one, with ties
    broken by the HIGHEST-CONFIDENCE segment (so a 1-1 split still resolves)."""
    vals = [(s.get("llm", {}).get(field), float(s.get("llm", {}).get("confidence") or 0))
            for s in segments if s.get("llm", {}).get(field)]
    if not vals:
        return None
    counts = Counter(v for v, _ in vals)
    top, n = counts.most_common(1)[0]
    if list(counts.values()).count(n) > 1:        # tie -> highest-confidence segment wins
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


def tag_segments(payload: dict, route_path: str, cfg: dict, device: str) -> None:
    """Tag every segment in place (payload['segments'][i]['llm'])."""
    import torch
    from transformers import (AutoModelForCausalLM, AutoTokenizer,
                              BitsAndBytesConfig)

    language = payload.get("language") or "unknown"
    is_silent = route_path == SILENT
    with managed_model("Qwen2.5-7B (4-bit)") as keep:
        bnb = BitsAndBytesConfig(load_in_4bit=True,
                                 bnb_4bit_compute_dtype=torch.float16,
                                 bnb_4bit_quant_type="nf4",
                                 bnb_4bit_use_double_quant=True)
        tok = keep(AutoTokenizer.from_pretrained(cfg["LLM_MODEL"]))
        llm = keep(AutoModelForCausalLM.from_pretrained(
            cfg["LLM_MODEL"], quantization_config=bnb, device_map="auto",
            torch_dtype=torch.float16))
        for i, seg in enumerate(payload["segments"]):
            prompt = (_silent_prompt(seg, language) if is_silent
                      else _voice_prompt(seg, language))
            text = tok.apply_chat_template(
                [{"role": "system",
                  "content": "You are a precise educational video tagging engine."},
                 {"role": "user", "content": prompt}],
                tokenize=False, add_generation_prompt=True)
            inp = tok(text, return_tensors="pt").to(llm.device)
            with torch.no_grad():
                out = llm.generate(**inp,
                                   max_new_tokens=cfg["LLM_MAX_NEW_TOKENS"],
                                   do_sample=False, pad_token_id=tok.eos_token_id)
            raw = tok.decode(out[0][inp.input_ids.shape[1]:], skip_special_tokens=True)
            seg["llm"] = _parse_llm(raw)
            log(f"seg {i}: topic={seg['llm'].get('topic')!r} "
                f"subject={seg['llm'].get('subject')!r}")

    _consistency_pass(payload["segments"])


def embed_segments(payload: dict, embedder) -> np.ndarray:
    """Embed each segment (LLM summary, or transcript/OCR fallback) for search."""
    texts = []
    for s in payload["segments"]:
        llm = s.get("llm", {})
        texts.append(llm.get("summary") or s.get("text") or s.get("ocr") or
                     (s.get("captions") or [""])[0] or "untitled segment")
    if not texts:
        return np.zeros((0, 384))
    return embedder.encode(texts, normalize_embeddings=True)
