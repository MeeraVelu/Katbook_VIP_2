"""
llm_backend.py — pluggable tagging LLM backends.

The pipeline's tagging stage asks an instruction LLM to turn each segment's
signals into strict JSON. Where that LLM *runs* is now a config choice
(``TAGGING_BACKEND``), decoupled from the prompts and the JSON contract:

* ``vllm``      — call a vLLM OpenAI-compatible server over HTTP (production;
                  Qwen2.5-7B-Instruct FP8 on Blackwell). Swapping to 14B is a
                  ``VLLM_MODEL`` change, not a code change. No model in-process.
* ``inprocess`` — load the model with transformers in the worker process
                  (FP16 by default; optional 4-bit via bitsandbytes for small
                  GPUs). Preserves the POC path for environments without vLLM.
* ``stub``      — deterministic, dependency-free tagging for the CPU smoke test
                  and CI (no model download, no GPU).

Every backend is a context manager exposing ``.generate(system, prompt,
max_new_tokens) -> str`` returning raw model text; the caller parses/validates.
For ``inprocess`` the heavy model is loaded on ``__enter__`` and freed on
``__exit__`` via :func:`utils.managed_model`, preserving one-model-at-a-time VRAM.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from contextlib import contextmanager

from .utils import log, managed_model


class VLLMBackend:
    """OpenAI-compatible client hitting a vLLM server. Holds no GPU memory here."""

    def __init__(self, base_url: str, model: str, api_key: str = "EMPTY"):
        from openai import OpenAI

        self._client = OpenAI(base_url=base_url, api_key=api_key or "EMPTY", timeout=120)
        self._model = model
        log(f"tagging backend = vLLM ({model} @ {base_url})")

    def generate(self, system: str, prompt: str, max_new_tokens: int) -> str:
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=max_new_tokens,
        )
        return (resp.choices[0].message.content or "").strip()


class InprocessBackend:
    """transformers CausalLM in-process. FP16 on CUDA; optional 4-bit; FP32 on CPU."""

    def __init__(self, model_name: str, device: str, use_4bit: bool = False):
        self._model_name = model_name
        self._device = device
        self._use_4bit = use_4bit
        self._tok = None
        self._model = None
        self._keep = None

    def _load(self, keep) -> None:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self._keep = keep
        self._tok = keep(AutoTokenizer.from_pretrained(self._model_name))
        kwargs: dict = {}
        if self._device == "cuda":
            kwargs["device_map"] = "auto"
            if self._use_4bit:
                try:
                    from transformers import BitsAndBytesConfig

                    kwargs["quantization_config"] = BitsAndBytesConfig(
                        load_in_4bit=True,
                        bnb_4bit_compute_dtype=torch.float16,
                        bnb_4bit_quant_type="nf4",
                        bnb_4bit_use_double_quant=True,
                    )
                    log("inprocess LLM: 4-bit (bitsandbytes)")
                except Exception as e:  # bitsandbytes missing -> plain FP16
                    log(f"4-bit unavailable ({str(e)[:50]}); FP16", "WARN")
                    kwargs["torch_dtype"] = torch.float16
            else:
                kwargs["torch_dtype"] = torch.float16
        else:
            kwargs["torch_dtype"] = torch.float32
        self._model = keep(AutoModelForCausalLM.from_pretrained(self._model_name, **kwargs))
        if self._device != "cuda":
            self._model = self._model.to("cpu")
        log(f"tagging backend = inprocess ({self._model_name}, device={self._device})")

    def generate(self, system: str, prompt: str, max_new_tokens: int) -> str:
        import torch

        text = self._tok.apply_chat_template(
            [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            tokenize=False,
            add_generation_prompt=True,
        )
        inp = self._tok(text, return_tensors="pt").to(self._model.device)
        with torch.no_grad():
            out = self._model.generate(
                **inp,
                max_new_tokens=max_new_tokens,
                do_sample=False,
                pad_token_id=self._tok.eos_token_id,
            )
        return self._tok.decode(out[0][inp.input_ids.shape[1] :], skip_special_tokens=True).strip()


class StubBackend:
    """Deterministic tagger for smoke/CI: emits schema-valid JSON from the prompt.

    It reads whatever transcript/OCR text is embedded in the prompt and echoes a
    short topic, so the full pipeline wiring (parse -> finalize -> store -> export)
    is exercised end-to-end without downloading or running any model."""

    def generate(self, system: str, prompt: str, max_new_tokens: int) -> str:
        m = re.search(r'"""(.*?)"""', prompt, re.DOTALL)
        if not m:
            m = re.search(r"On-screen text \(OCR[^:]*:\s*(.+)", prompt)
        snippet = (m.group(1) if m else "").strip()
        words = re.findall(r"[A-Za-z][A-Za-z'-]+", snippet)[:6]
        topic = " ".join(words[:4]).title() or "Sample Lesson"
        is_silent = "NO narration" in prompt or "no speech" in prompt
        return json.dumps(
            {
                "topic": topic,
                "subtopics": [w.lower() for w in words[:3]],
                "content_type": "animation" if is_silent else "lecture",
                "difficulty": "beginner",
                "grade_level": "Grade 1-2",
                "subject": "General Knowledge",
                "summary": f"Auto stub summary for: {topic}.",
                "tags": [w.lower() for w in words[:5]],
                "speaker_role": "narrator" if is_silent else "teacher",
                "language": "en",
                "has_visual_content": True,
                "confidence": 0.5 if is_silent else 0.7,
                "bloom_level": "understand",
                "learning_objectives": [f"Students will be able to describe {topic}."],
                "est_min": 2.0,
            }
        )


def _resolve_backend_name(cfg: dict, device: str) -> str:
    name = cfg.get("TAGGING_BACKEND")
    if name:
        return name
    # sensible default: vLLM only makes sense with a URL; otherwise in-process.
    return "vllm" if cfg.get("VLLM_BASE_URL") and device == "cuda" else "inprocess"


@contextmanager
def get_backend(cfg: dict, device: str) -> Iterator[object]:
    """Yield a ready tagging backend. For ``inprocess`` the model is loaded inside
    ``managed_model`` so it is freed (and VRAM cleared) when the block exits."""
    name = _resolve_backend_name(cfg, device)
    if name == "vllm":
        yield VLLMBackend(
            cfg["VLLM_BASE_URL"],
            cfg.get("VLLM_MODEL") or cfg["LLM_MODEL"],
            cfg.get("VLLM_API_KEY", "EMPTY"),
        )
        return
    if name == "stub":
        yield StubBackend()
        return
    if name == "inprocess":
        use_4bit = bool(
            cfg.get(
                "INPROCESS_4BIT",
                device == "cuda" and cfg.get("PROFILE") in ("fast", "balanced", "quality"),
            )
        )
        backend = InprocessBackend(cfg["LLM_MODEL"], device, use_4bit=use_4bit)
        with managed_model(f"LLM inprocess ({cfg['LLM_MODEL']})") as keep:
            backend._load(keep)
            yield backend
        return
    raise ValueError(f"Unknown TAGGING_BACKEND {name!r} (vllm|inprocess|stub)")
