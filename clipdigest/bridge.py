"""Comprehension dependency resolution (LLM pass 2) — the differentiator.

Given the selected clips AND the full transcript, find references in kept clips
whose setup lives only in the dropped material, and resolve each as either a
`pull_in` (re-include a short setup slice) or a `bridge` (a one-line overlay).
Also produce a global `primer`.
"""

from __future__ import annotations

from .llm import LLMClient
from .select import format_transcript

VALID_KINDS = {"referential", "definitional", "causal", "setup_payoff", "numeric"}

SYSTEM = (
    "You ensure a condensed video cut stays comprehensible. You find places where "
    "a KEPT clip depends on something explained ONLY in the DROPPED portion, and you "
    "fix each gap as cheaply as possible. You reply with JSON only."
)


def _selected_block(clips: list[dict]) -> str:
    return "\n".join(
        f"- clip {i}: [{c['start_sec']:.1f}-{c['end_sec']:.1f}] {c['reason']}"
        for i, c in enumerate(clips)
    )


def _prompt(transcript_text: str, clips: list[dict], focus: str | None) -> str:
    focus_line = f'\nThe cut focuses on: "{focus}".\n' if focus else ""
    return (
        "FULL TRANSCRIPT (`[start-end] text`, seconds):\n"
        f"{transcript_text}\n\n"
        "CLIPS BEING KEPT (everything else is dropped):\n"
        f"{_selected_block(clips)}\n"
        f"{focus_line}\n"
        "For each kept clip, look for dangling references whose antecedent/setup is "
        "ONLY in the dropped portion:\n"
        "- referential: a pronoun / 'that company' / 'the second one' with no kept antecedent\n"
        "- definitional: a term defined earlier, used bare later\n"
        "- causal: 'which is why...' where the cause/chain was set up earlier\n"
        "- setup_payoff: a callback whose setup was cut\n"
        "- numeric: a comparison ('3x better') against an earlier baseline\n\n"
        "Resolve each gap. A card is a COST to the viewer — be conservative and only "
        "flag gaps an attentive viewer genuinely could not infer.\n"
        "- pull_in: re-include a short (<= ~25s) setup slice from the dropped portion. "
        "Prefer this for whole-narrative setups.\n"
        "- bridge: a single on-screen line. Prefer this for one name/term/number. "
        "`anchor_sec` is the moment (in original seconds) the reference LANDS in a kept "
        "clip. `text` is <= ~14 words. `pause` = true only if the point is dense enough "
        "to warrant briefly pausing the video.\n\n"
        "Also give a `primer`: <= 2 sentences of global setup the whole cut assumes.\n\n"
        "Reply with ONLY this JSON:\n"
        "{\n"
        '  "primer": "<<= 2 sentences>",\n'
        '  "pull_ins": [{"start_sec": <n>, "end_sec": <n>, "reason": "<phrase>"}],\n'
        '  "bridges": [{"anchor_sec": <n>, "text": "<line>", "kind": '
        '"referential|definitional|causal|setup_payoff|numeric", "pause": <bool>}]\n'
        "}"
    )


def resolve_comprehension(
    transcript: list[dict],
    clips: list[dict],
    focus: str | None,
    llm: LLMClient,
    duration: float,
) -> dict:
    prompt = _prompt(format_transcript(transcript), clips, focus)
    data = llm.json(SYSTEM, prompt)
    if not isinstance(data, dict):
        data = {}
    return {
        "primer": str(data.get("primer", "")).strip(),
        "pull_ins": _clean_pull_ins(data.get("pull_ins"), duration),
        "bridges": _clean_bridges(data.get("bridges"), duration),
    }


def _clean_pull_ins(raw, duration: float) -> list[dict]:
    out = []
    for p in raw or []:
        try:
            start = max(0.0, float(p["start_sec"]))
            end = min(float(p["end_sec"]), duration) if duration else float(p["end_sec"])
        except (KeyError, TypeError, ValueError):
            continue
        if end - start < 0.5:
            continue
        out.append(
            {
                "start_sec": round(start, 2),
                "end_sec": round(end, 2),
                "reason": str(p.get("reason", "")).strip() or "setup (pulled in)",
                "score": 0.6,
            }
        )
    return out


def _clean_bridges(raw, duration: float) -> list[dict]:
    out = []
    for b in raw or []:
        try:
            anchor = float(b["anchor_sec"])
        except (KeyError, TypeError, ValueError):
            continue
        if duration:
            anchor = min(anchor, duration)
        text = str(b.get("text", "")).strip()
        if not text:
            continue
        kind = str(b.get("kind", "referential")).strip().lower()
        if kind not in VALID_KINDS:
            kind = "referential"
        out.append(
            {
                "anchor_sec": round(max(0.0, anchor), 2),
                "text": text,
                "kind": kind,
                "pause": bool(b.get("pause", False)),
            }
        )
    return out
