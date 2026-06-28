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


def _split_max_duration(segs: list[dict], max_sec: float, min_sec: float) -> list[dict]:
    """Force-split any segment longer than max_sec into ~equal sub-segments.

    Semantic boundary detection can under-segment a smooth lecture into one giant
    block (e.g. a single 3.5-minute segment covering six subtopics). This caps the
    damage: a too-long segment is divided into the fewest equal parts that each
    land at/under max_sec, without producing a part shorter than min_sec.
    """
    if not max_sec or max_sec <= 0:
        return segs
    out: list[dict] = []
    for s in segs:
        dur = s["end"] - s["start"]
        if dur <= max_sec:
            out.append(dict(s)); continue
        n = int(round(dur / max_sec)) or 1
        # never slice so fine that a part drops below the min-duration floor
        n = min(n, max(1, int(dur // max(min_sec, 1))))
        if n <= 1:
            out.append(dict(s)); continue
        step = dur / n
        for k in range(n):
            a = s["start"] + k * step
            b = s["end"] if k == n - 1 else s["start"] + (k + 1) * step
            out.append({"start": round(a, 2), "end": round(b, 2)})
    return out


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
    segs = _split_max_duration(segs, cfg.get("MAX_SEGMENT_SEC", 0),
                               cfg["MIN_SEGMENT_SEC"])
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
    segs = _split_max_duration(segs, cfg.get("MAX_SEGMENT_SEC", 0),
                               cfg["MIN_SEGMENT_SEC"])
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
