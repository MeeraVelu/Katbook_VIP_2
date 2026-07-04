"""LLM tagging: JSON parse/recovery robustness, field finalization, the stub
backend, the consistency pass, and end-to-end tagging with the stub (no model)."""

from __future__ import annotations

import numpy as np

from pipeline import tagging
from pipeline.config import load_config
from pipeline.llm_backend import StubBackend, get_backend

CFG = load_config({"PROFILE": "smoke"})  # TAGGING_BACKEND=stub


def test_parse_clean_json():
    d = tagging._parse_llm('{"topic": "Fractions", "subject": "Mathematics"}')
    assert d["topic"] == "Fractions" and d["subject"] == "Mathematics"


def test_parse_strips_code_fences():
    d = tagging._parse_llm('```json\n{"topic": "Photosynthesis"}\n```')
    assert d["topic"] == "Photosynthesis"


def test_parse_recovers_truncated_output():
    # truncated mid-key AFTER a closed tags list -> brace-completion fails, so the
    # field-by-field regex recovery kicks in and still recovers topic + tags.
    raw = '{"topic": "Balancing Equations", "subject": "Chemistry", "tags": ["acid", "base"], "confiden'
    d = tagging._parse_llm(raw)
    assert d["topic"] == "Balancing Equations"
    assert d.get("_recovered") is True
    assert "acid" in d.get("tags", [])


def test_parse_total_garbage_reports_error():
    d = tagging._parse_llm("no json here at all")
    assert "_parse_error" in d


def test_finalize_defaults_confidence_by_path():
    silent = tagging._finalize_fields({"topic": "x"}, is_silent=True)
    voice = tagging._finalize_fields({"topic": "x"}, is_silent=False)
    assert silent["confidence"] <= 0.6 and silent["confidence_defaulted"]
    assert voice["confidence"] == 0.7


def test_silent_confidence_capped():
    d = tagging._finalize_fields({"topic": "x", "confidence": 0.95}, is_silent=True)
    assert d["confidence"] <= 0.6


def test_consistency_pass_unifies_subject():
    segs = [
        {"llm": {"subject": "Chemistry", "grade_level": "Grade 9-10", "confidence": 0.9}},
        {"llm": {"subject": "Chemistry", "grade_level": "Grade 9-10", "confidence": 0.8}},
        {"llm": {"subject": "Mathematics", "grade_level": "Grade 7-8", "confidence": 0.4}},
    ]
    tagging._consistency_pass(segs)
    assert segs[2]["llm"]["subject"] == "Chemistry"
    assert segs[2]["llm"]["subject_raw"] == "Mathematics"


def test_stub_backend_emits_valid_schema():
    out = StubBackend().generate("sys", 'TRANSCRIPT:\n"""atoms bond together"""', 256)
    import json

    d = json.loads(out)
    for key in ("topic", "subject", "summary", "tags", "confidence", "content_type"):
        assert key in d


def test_tag_segments_end_to_end_with_stub():
    payload = {
        "language": "en",
        "segments": [
            {
                "start": 0,
                "end": 60,
                "text": "the water cycle and evaporation",
                "ocr": "",
                "scenes": [],
                "objects": [],
            },
            {
                "start": 60,
                "end": 120,
                "text": "condensation and rain",
                "ocr": "",
                "scenes": [],
                "objects": [],
            },
        ],
    }
    tagging.tag_segments(payload, "voice", CFG, "cpu")
    for s in payload["segments"]:
        assert s["llm"].get("topic")
        assert "_parse_error" not in s["llm"]


def test_get_backend_stub_is_contextmanager():
    with get_backend(CFG, "cpu") as backend:
        assert isinstance(backend, StubBackend)


class _FakeEmbedder:
    def get_sentence_embedding_dimension(self):
        return 8

    def encode(self, texts, normalize_embeddings=True):
        return np.ones((len(texts), 8), dtype="float32")


def test_embed_segments_uses_summary_then_fallback():
    payload = {
        "segments": [
            {"llm": {"summary": "a summary"}, "text": "t"},
            {"llm": {}, "text": "fallback text"},
        ]
    }
    emb = tagging.embed_segments(payload, _FakeEmbedder())
    assert emb.shape == (2, 8)


def test_embed_segments_empty_uses_embedder_dim():
    emb = tagging.embed_segments({"segments": []}, _FakeEmbedder())
    assert emb.shape == (0, 8)
