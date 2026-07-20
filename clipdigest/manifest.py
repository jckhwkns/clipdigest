"""Pad, merge, budget, and assemble the manifest.

The manifest is the whole "edit": a video id plus ordered padded segments in
ORIGINAL time, a primer, and bridges whose anchors are translated into the
CONDENSED timeline the viewer actually experiences.
"""

from __future__ import annotations

import json
import os

from . import config


def build_manifest(
    video_id: str,
    source_url: str,
    target_minutes: float,
    clips: list[dict],
    comprehension: dict,
    duration: float,
) -> dict:
    """Turn raw clips + comprehension data into the final manifest dict."""
    # Pull-ins are just extra clips; merging resolves any overlap with kept clips.
    all_clips = clips + comprehension.get("pull_ins", [])
    padded = _pad(all_clips, duration)
    segments = _merge(padded)
    segments = _budget(segments, target_minutes)

    condensed_sec = sum(s["end_sec"] - s["start_sec"] for s in segments)
    bridges = _place_bridges(comprehension.get("bridges", []), segments)

    return {
        "video_id": video_id,
        "source_url": source_url,
        "target_minutes": target_minutes,
        "primer": comprehension.get("primer", ""),
        "segments": [
            {
                "start_sec": round(s["start_sec"], 2),
                "end_sec": round(s["end_sec"], 2),
                "reason": s["reason"],
            }
            for s in segments
        ],
        "bridges": bridges,
        "stats": {
            "original_sec": round(duration, 1),
            "condensed_sec": round(condensed_sec, 1),
            "percent_kept": round(100 * condensed_sec / duration, 1) if duration else 0,
        },
    }


# --- Steps -------------------------------------------------------------------
def _pad(clips: list[dict], duration: float) -> list[dict]:
    out = []
    for c in clips:
        start = max(0.0, c["start_sec"] - config.PAD_START)
        end = c["end_sec"] + config.PAD_END
        if duration:
            end = min(end, duration)
        out.append({**c, "start_sec": start, "end_sec": end})
    out.sort(key=lambda c: c["start_sec"])
    return out


def _merge(clips: list[dict]) -> list[dict]:
    """Merge overlapping/touching clips; keep the strongest reason and score."""
    merged: list[dict] = []
    for c in clips:
        if merged and c["start_sec"] <= merged[-1]["end_sec"]:
            prev = merged[-1]
            prev["end_sec"] = max(prev["end_sec"], c["end_sec"])
            # Carry the reason/score of the higher-value contributor.
            if c["score"] > prev["score"]:
                prev["reason"], prev["score"] = c["reason"], c["score"]
        else:
            merged.append(dict(c))
    return merged


def _budget(segments: list[dict], target_minutes: float) -> list[dict]:
    """If we run more than tolerance over target, drop lowest-value segments."""
    ceiling = target_minutes * 60 * (1 + config.OVER_TARGET_TOLERANCE)
    total = sum(s["end_sec"] - s["start_sec"] for s in segments)
    if total <= ceiling or len(segments) <= 1:
        return segments
    # Repeatedly remove the lowest-scoring segment until under the ceiling.
    kept = list(segments)
    while total > ceiling and len(kept) > 1:
        victim = min(kept, key=lambda s: s["score"])
        kept.remove(victim)
        total -= victim["end_sec"] - victim["start_sec"]
    kept.sort(key=lambda s: s["start_sec"])
    return kept


# --- Bridge placement (original -> condensed time) ---------------------------
def _place_bridges(bridges: list[dict], segments: list[dict]) -> list[dict]:
    """Translate each bridge anchor from original time to condensed time.

    Anchors that fall inside a trimmed/merged gap snap to the start of the next
    kept segment; anchors past the end snap to the final condensed moment.
    """
    placed = []
    for b in bridges:
        cond = _to_condensed(b["anchor_sec"], segments)
        if cond is None:
            continue  # nothing kept after the anchor; the reference never plays
        placed.append(
            {
                "anchor_sec": round(cond, 2),
                "text": b["text"],
                "kind": b["kind"],
                "pause": b["pause"],
            }
        )
    placed.sort(key=lambda b: b["anchor_sec"])
    return placed


def _to_condensed(t: float, segments: list[dict]) -> float | None:
    offset = 0.0
    for s in segments:
        length = s["end_sec"] - s["start_sec"]
        if t < s["start_sec"]:
            return offset  # anchor sits in a gap -> start of this next segment
        if t <= s["end_sec"]:
            return offset + (t - s["start_sec"])
        offset += length
    return None  # anchor is after the last kept segment


# --- IO ----------------------------------------------------------------------
def write_manifest(manifest: dict, out_dir: str) -> str:
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "manifest.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)
    return path
