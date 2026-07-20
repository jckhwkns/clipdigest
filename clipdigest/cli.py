"""Command-line entry point: transcript -> selection -> comprehension -> viewer."""

from __future__ import annotations

import argparse
import sys

from . import bridge, manifest as manifest_mod, render, select, transcript as transcript_mod
from .llm import LLMClient, LLMError
from .transcript import TranscriptError


def _log(msg: str) -> None:
    print(f"clipdigest: {msg}", file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="clipdigest",
        description="Turn a long YouTube video into a condensed, comprehension-preserving viewer.",
    )
    p.add_argument("url", help="YouTube URL or 11-char video id")
    p.add_argument("--minutes", type=float, required=True,
                   help="target duration of the condensed cut, in minutes")
    p.add_argument("--focus", default=None,
                   help='free-text steer, e.g. "the funding history and the pivot"')
    p.add_argument("--out", default="./output", help="output directory (default ./output)")
    return p


def run(args: argparse.Namespace) -> int:
    if args.minutes <= 0:
        _log("--minutes must be positive.")
        return 2

    # 1. Transcript ----------------------------------------------------------
    try:
        video_id = transcript_mod.extract_video_id(args.url)
        _log(f"fetching transcript for {video_id} ...")
        transcript = transcript_mod.fetch_transcript(video_id)
    except TranscriptError as exc:
        _log(str(exc))
        return 1
    duration = transcript_mod.transcript_duration(transcript)
    _log(f"transcript: {len(transcript)} segments, ~{duration/60:.1f} min of source")

    source_url = f"https://www.youtube.com/watch?v={video_id}"

    # Target longer than source: keep the whole thing, skip the LLM passes.
    if duration and args.minutes * 60 >= duration:
        _log("target >= source length; keeping the entire video.")
        clips = [{"start_sec": 0.0, "end_sec": duration, "reason": "full video", "score": 1.0}]
        comprehension = {"primer": "", "pull_ins": [], "bridges": []}
    else:
        try:
            llm = LLMClient()
            _log(f"selecting segments via {llm.provider}/{llm.model} ...")
            clips = select.select_clips(transcript, args.minutes, args.focus, llm, duration)
            _log(f"selected {len(clips)} clips; resolving comprehension gaps ...")
            comprehension = bridge.resolve_comprehension(transcript, clips, args.focus, llm, duration)
            _log(f"primer + {len(comprehension['bridges'])} bridges, "
                 f"{len(comprehension['pull_ins'])} pull-ins")
        except LLMError as exc:
            _log(str(exc))
            return 1
        except ValueError as exc:
            _log(f"selection failed: {exc}")
            return 1

    # 4/5. Pad, merge, budget, assemble -------------------------------------
    manifest = manifest_mod.build_manifest(
        video_id, source_url, args.minutes, clips, comprehension, duration
    )
    st = manifest["stats"]
    _log(f"condensed to {st['condensed_sec']/60:.1f} min "
         f"({st['percent_kept']}% kept) across {len(manifest['segments'])} segments")

    # 6. Emit ----------------------------------------------------------------
    mpath = manifest_mod.write_manifest(manifest, args.out)
    hpath = render.render(manifest, args.out)
    _log(f"wrote {mpath}")
    _log(f"wrote {hpath}")
    print(hpath)  # stdout: the artifact to open
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except KeyboardInterrupt:  # pragma: no cover
        _log("interrupted.")
        return 130


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
