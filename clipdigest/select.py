"""Segment selection (LLM pass 1).

Given the full timestamped transcript, ask the editor-LLM which spans to keep.
"""

from __future__ import annotations

from . import config
from .llm import LLMClient


def format_transcript(transcript: list[dict]) -> str:
    """Render `[start-end] text` lines the LLM can reference by timestamp."""
    lines = []
    for seg in transcript:
        start = seg["start"]
        end = start + seg["duration"]
        lines.append(f"[{start:.1f}-{end:.1f}] {seg['text']}")
    return "\n".join(lines)


SYSTEM = (
    "You are a sharp video editor. You condense long talks into a shorter cut "
    "that keeps only the most substantive, self-contained, worthwhile material. "
    "You reply with JSON only."
)


def _prompt(transcript_text: str, target_minutes: float, focus: str | None, budget_minutes: float) -> str:
    focus_line = (
        f'The viewer cares specifically about: "{focus}". Prioritise that, but keep '
        "whatever is needed for it to make sense.\n"
        if focus
        else "No specific focus given. Select on what is most substantive on its own.\n"
    )
    return (
        f"Below is a timestamped transcript. Each line is `[start-end] text` in seconds.\n\n"
        f"Target condensed length: about {target_minutes:g} minutes.\n"
        f"Select clips whose durations SUM to about {budget_minutes:.1f} minutes "
        f"(we pad each clip afterward, which adds time back).\n"
        f"{focus_line}\n"
        "Rules:\n"
        "- Keep only complete thoughts. Boundaries must fall between sentences, never mid-word.\n"
        "- Clips must be in chronological order and must not overlap.\n"
        "- Prefer fewer, longer coherent clips over many tiny fragments.\n"
        "- `reason` is a short phrase (<= 8 words) describing what the clip covers.\n"
        "- `score` is 0.0-1.0, how essential the clip is (used to trim if we run long).\n\n"
        "Reply with ONLY this JSON:\n"
        '{"clips": [{"start_sec": <number>, "end_sec": <number>, '
        '"reason": "<phrase>", "score": <0..1>}]}\n\n'
        "TRANSCRIPT:\n"
        f"{transcript_text}"
    )


def select_clips(
    transcript: list[dict],
    target_minutes: float,
    focus: str | None,
    llm: LLMClient,
    duration: float,
) -> list[dict]:
    budget_minutes = target_minutes * config.UNDER_TARGET_RATIO
    prompt = _prompt(format_transcript(transcript), target_minutes, focus, budget_minutes)
    data = llm.json(SYSTEM, prompt)
    clips_raw = data.get("clips", []) if isinstance(data, dict) else data
    clips = _clean(clips_raw, duration)
    if not clips:
        raise ValueError("The model returned no usable clips.")
    return clips


def _clean(clips_raw, duration: float) -> list[dict]:
    """Validate, clamp, drop degenerate clips, and sort chronologically."""
    cleaned = []
    for c in clips_raw or []:
        try:
            start = max(0.0, float(c["start_sec"]))
            end = float(c["end_sec"])
        except (KeyError, TypeError, ValueError):
            continue
        if duration:
            end = min(end, duration)
        if end - start < 0.5:  # ignore zero/negative/absurdly tiny spans
            continue
        cleaned.append(
            {
                "start_sec": round(start, 2),
                "end_sec": round(end, 2),
                "reason": str(c.get("reason", "")).strip() or "segment",
                "score": _score(c.get("score")),
            }
        )
    cleaned.sort(key=lambda c: c["start_sec"])
    return cleaned


def _score(value) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.5
