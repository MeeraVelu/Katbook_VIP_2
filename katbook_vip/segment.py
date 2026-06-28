"""
segment.py — Stage 5. Cut the video into coherent time segments and attach the
per-segment signals the tagger needs.

Two paths:
  * VOICED  -> semantic segmentation: cosine-similarity drop between adjacent
    transcript windows, threshold picked by the knee of the sorted drops. The
    min-duration guard is fixed to merge by *duration* (the old code merged by
    distance-from-segment-start, which collapsed everything into ~2 chunks).
  * SILENT  -> visual segmentation: group consecutive frames with the same scene
    label; merge to respect min-duration. (No transcript to segment on.)

Both honour MIN_SEGMENT_SEC and MAX_SEGMENTS.
"""
from __future__ import annotations

import numpy as np


def _merge_min_duration(segs: list[dict], min_sec: float) -> list[dict]:
    """Merge a segment into the previous one if IT is shorter than min_sec."""
    merged: list[dict] = []
    for s in segs:
        if merged and (s["end"] - s["start"]) < min_sec:
            merged[-1]["end"] = s["end"]
        elif merged and (merged[-1]["end"] - merged[-1]["start"]) < min_sec:
            merged[-1]["end"] = s["end"]
        else:
            merged.append(dict(s))
    return merged


def _cap_segments(segs: list[dict], max_segments: int) -> list[dict]:
    """If over the cap, greedily merge the shortest neighbours until within cap."""
    segs = [dict(s) for s in segs]
    while len(segs) > max_segments:
        # find shortest segment, merge it into its shorter-duration neighbour
        i = min(range(len(segs)), key=lambda k: segs[k]["end"] - segs[k]["start"])
        if i == 0:
            segs[0]["end"] = segs[1]["end"]; del segs[1]
        elif i == len(segs) - 1:
            segs[-2]["end"] = segs[-1]["end"]; del segs[-1]
        else:
            left = segs[i - 1]["end"] - segs[i - 1]["start"]
            right = segs[i + 1]["end"] - segs[i + 1]["start"]
            if left <= right:
                segs[i - 1]["end"] = segs[i]["end"]; del segs[i]
            else:
                segs[i]["end"] = segs[i + 1]["end"]; del segs[i + 1]
    return segs


def segment_voiced(windows: list[dict], win_emb: np.ndarray, duration: float,
                   cfg: dict) -> list[dict]:
    if len(windows) <= 1:
        return [{"start": 0.0, "end": duration or
                 (windows[-1]["end"] if windows else 0.0)}]
    sims = [float(np.dot(win_emb[i], win_emb[i + 1])) for i in range(len(win_emb) - 1)]
    drops = [1 - s for s in sims]
    thresh = cfg["SIM_DROP_FALLBACK"]
    try:
        from kneed import KneeLocator
        sd = sorted(drops)
        kn = KneeLocator(range(len(sd)), sd, curve="convex", direction="increasing")
        if kn.knee is not None:
            thresh = max(sd[kn.knee], 0.15)
    except Exception:
        pass
    bounds = sorted(set([0] + [i + 1 for i, d in enumerate(drops) if d >= thresh]
                        + [len(windows)]))
    segs = [{"start": windows[a]["start"], "end": windows[b - 1]["end"]}
            for a, b in zip(bounds[:-1], bounds[1:])]
    segs = _merge_min_duration(segs, cfg["MIN_SEGMENT_SEC"])
    return _cap_segments(segs, cfg["MAX_SEGMENTS"])


def segment_silent(frames: list[dict], duration: float, cfg: dict) -> list[dict]:
    """Group consecutive same-scene frames into segments (visual segmentation)."""
    if not frames:
        return [{"start": 0.0, "end": duration}]
    segs, cur = [], {"start": 0.0, "scene": frames[0].get("scene")}
    for f in frames:
        if f.get("scene") != cur["scene"]:
            segs.append({"start": cur["start"], "end": f["time"]})
            cur = {"start": f["time"], "scene": f.get("scene")}
    segs.append({"start": cur["start"], "end": duration})
    segs = _merge_min_duration(segs, cfg["MIN_SEGMENT_SEC"])
    return _cap_segments(segs, cfg["MAX_SEGMENTS"])


def attach_signals(segs: list[dict], transcript: list[dict],
                   frames: list[dict]) -> list[dict]:
    """Populate each segment with its transcript text + aggregated visual signals."""
    for s in segs:
        s["text"] = " ".join(t["text"] for t in transcript
                             if s["start"] <= t["start"] < s["end"])
        sf = [f for f in frames if s["start"] <= f["time"] < s["end"]]
        s["scenes"] = sorted({f["scene"] for f in sf if f.get("scene")})
        s["objects"] = sorted({o for f in sf for o in f.get("objects", [])})
        s["ocr"] = " ".join(f.get("ocr", "") for f in sf if f.get("ocr"))[:600]
        s["captions"] = [f["caption"] for f in sf if f.get("caption")][:4]
    return segs
