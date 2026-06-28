"""
nlp_stage.py — Stage 3. Lightweight NLP enrichment of the transcript: named
entities, keyphrases, and the 30 s window embeddings that segmentation reuses.

The embedder is a small 384-d MiniLM loaded ONCE for the whole batch (passed in),
so this stage adds almost no per-video cost. KeyBERT can break on certain
sentence-transformers versions, so a dependency-light spaCy noun-chunk extractor
is the fallback.
"""
from __future__ import annotations
from collections import Counter

import numpy as np

from .utils import free_vram


def _fallback_keywords(doc, top_n: int = 20):
    chunks = [c.text.lower().strip() for c in doc.noun_chunks
              if 2 <= len(c.text.strip()) <= 40]
    cnt = Counter(chunks)
    n = sum(cnt.values()) or 1
    return [(t, round(c / n, 3)) for t, c in cnt.most_common(top_n)]


def enrich(full_text: str, embedder, nlp) -> dict:
    """Entities + keywords from the transcript. Empty-safe for silent videos."""
    if not full_text.strip():
        return {"entities": [], "keywords": []}
    doc = nlp(full_text[:100000])
    entities = sorted(set((e.text, e.label_) for e in doc.ents))[:40]
    try:
        from keybert import KeyBERT
        kws = KeyBERT(model=embedder).extract_keywords(
            full_text, keyphrase_ngram_range=(1, 2), stop_words="english", top_n=20)
    except Exception:
        kws = _fallback_keywords(doc)
    return {"entities": [{"text": t, "label": l} for t, l in entities],
            "keywords": [{"term": k, "score": round(float(s), 3)} for k, s in kws]}


def build_windows(transcript: list[dict], win: int) -> list[dict]:
    if not transcript:
        return []
    end_t = transcript[-1]["end"]
    out, t = [], 0.0
    while t < end_t:
        chunk = " ".join(s["text"] for s in transcript if t <= s["start"] < t + win)
        out.append({"start": t, "end": min(t + win, end_t), "text": chunk})
        t += win
    return [w for w in out if w["text"].strip()]


def embed_windows(windows: list[dict], embedder) -> np.ndarray:
    if not windows:
        return np.zeros((0, 384))
    return embedder.encode([w["text"] for w in windows], normalize_embeddings=True)
