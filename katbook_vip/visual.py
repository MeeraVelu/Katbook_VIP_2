"""
visual.py — Stage 2B. Per-frame visual understanding, with two production
upgrades over the old loop:

1. SPEED: CLIP runs as a single batched forward pass over all frames instead of
   one Python call per frame. YOLO and OCR are GATED by the CLIP scene label so
   they only run where they add value.

2. QUALITY: YOLO is suppressed on synthetic scenes (animation / diagram / slide),
   which is where it invents objects ("apple", "sports ball", "tv" on a pendulum
   cartoon). This both removes the hallucinations and saves time. OCR runs only
   on text-likely frames (or every frame on the silent path, where on-screen text
   may be the only signal). BLIP-2 captioning is forced ON for silent videos.

Every model is loaded, used, and freed one at a time via `managed_model`, so a
16 GB T4 holds at most one heavy vision model at any moment.
"""
from __future__ import annotations
from collections import Counter
from pathlib import Path

from .utils import log, managed_model


def scene_is_realworld(scene: str | None, realworld: set) -> bool:
    return scene in realworld


def scene_is_texty(scene: str | None, texty: set) -> bool:
    return scene in texty


# --------------------------------------------------------------------------- #
# CLIP — batched zero-shot scene classification.
# --------------------------------------------------------------------------- #
def _clip_scenes(frames: list[dict], cfg: dict, device: str) -> None:
    from PIL import Image
    import torch
    from transformers import CLIPModel, CLIPProcessor

    labels = cfg["SCENE_LABELS"]
    with managed_model("CLIP") as keep:
        model = keep(CLIPModel.from_pretrained(cfg["CLIP_MODEL"]).to(device).eval())
        proc = keep(CLIPProcessor.from_pretrained(cfg["CLIP_MODEL"]))
        imgs = [Image.open(f["path"]).convert("RGB") for f in frames]
        with torch.no_grad():
            inp = proc(text=labels, images=imgs, return_tensors="pt",
                       padding=True).to(device)
            probs = model(**inp).logits_per_image.softmax(dim=1)  # [N, L]
        for fa, row in zip(frames, probs):
            top = int(row.argmax())
            fa["scene"] = labels[top]
            fa["scene_conf"] = round(float(row[top]), 3)


# --------------------------------------------------------------------------- #
# YOLO — only on real-world frames. Synthetic frames get objects=[] (no run).
# --------------------------------------------------------------------------- #
def _yolo_objects(frames: list[dict], cfg: dict, device: str) -> None:
    targets = [f for f in frames if scene_is_realworld(f.get("scene"),
                                                       cfg["REALWORLD_SCENES"])]
    for f in frames:
        f.setdefault("objects", [])
    if not targets:
        log("YOLO skipped: no real-world frames (all synthetic) -> 0 objects")
        return
    from ultralytics import YOLO
    with managed_model("YOLO") as keep:
        yolo = keep(YOLO(cfg["YOLO_MODEL"]))
        for f in targets:
            res = yolo(f["path"], verbose=False,
                       device=0 if device == "cuda" else "cpu")[0]
            f["objects"] = (sorted(set(res.names[int(c)]
                                       for c in res.boxes.cls.tolist()))
                            if res.boxes is not None else [])
    log(f"YOLO ran on {len(targets)}/{len(frames)} real-world frames")


# --------------------------------------------------------------------------- #
# OCR — multilingual, gated. Text-likely frames only, unless silent (then all).
# --------------------------------------------------------------------------- #
def _ocr_text(frames: list[dict], cfg: dict, device: str, run_all: bool) -> None:
    targets = (frames if run_all
               else [f for f in frames if scene_is_texty(f.get("scene"),
                                                          cfg["TEXTY_SCENES"])])
    for f in frames:
        f.setdefault("ocr", "")
    if not targets:
        log("OCR skipped: no text-likely frames")
        return
    import easyocr
    langs = cfg.get("OCR_LANGS", ["en"])
    with managed_model("OCR") as keep:
        try:
            reader = keep(easyocr.Reader(langs, gpu=(device == "cuda")))
        except Exception as e:  # e.g. Tamil state_dict mismatch -> English only
            log(f"OCR langs {langs} failed ({str(e)[:50]}); using ['en']", "WARN")
            reader = keep(easyocr.Reader(["en"], gpu=(device == "cuda")))
        for f in targets:
            try:
                f["ocr"] = " ".join(reader.readtext(f["path"], detail=0,
                                                    paragraph=True))[:500]
            except Exception:
                f["ocr"] = ""
    got = sum(1 for f in targets if f["ocr"])
    log(f"OCR ran on {len(targets)} frames; {got} had text")


# --------------------------------------------------------------------------- #
# BLIP-2 — frame captions. Forced ON for silent videos (often their only signal).
# --------------------------------------------------------------------------- #
def _blip_captions(frames: list[dict], cfg: dict, device: str, budget: int) -> None:
    for f in frames:
        f.setdefault("caption", "")
    if budget <= 0 or not frames:
        return
    from PIL import Image
    import torch
    from transformers import Blip2ForConditionalGeneration, Blip2Processor

    step = max(1, len(frames) // budget)
    chosen = frames[::step][:budget]
    with managed_model("BLIP-2") as keep:
        proc = keep(Blip2Processor.from_pretrained(cfg["BLIP2_MODEL"]))
        model = keep(Blip2ForConditionalGeneration.from_pretrained(
            cfg["BLIP2_MODEL"], torch_dtype=torch.float16).to(device).eval())
        with torch.no_grad():
            for f in chosen:
                img = Image.open(f["path"]).convert("RGB")
                inp = proc(images=img, return_tensors="pt").to(device, torch.float16)
                out = model.generate(**inp, max_new_tokens=40)
                f["caption"] = proc.batch_decode(out, skip_special_tokens=True)[0].strip()
    log(f"BLIP-2 captioned {len(chosen)} frames")


def analyze_frames(frames: list[dict], cfg: dict, device: str, *,
                   is_silent: bool) -> list[dict]:
    """
    Run the visual stack on the frames. On the silent path we OCR every frame and
    force captions on, because there is no transcript to fall back to.
    Returns the same list, enriched in place with scene/objects/ocr/caption.
    """
    if not frames:
        return frames
    _clip_scenes(frames, cfg, device)
    dist = Counter(f.get("scene") for f in frames)
    log(f"scenes: {dict(dist)}")
    _yolo_objects(frames, cfg, device)
    _ocr_text(frames, cfg, device, run_all=is_silent)
    caption_budget = cfg.get("CAPTION_FRAMES", 6) if is_silent else 0
    _blip_captions(frames, cfg, device, caption_budget)
    return frames
