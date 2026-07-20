"""Transcript acquisition.

Primary path: `youtube-transcript-api` (no video download).
Fallback: parse `yt-dlp` auto-sub VTT into the same shape.

A transcript is a list of segments: {"text": str, "start": float, "duration": float}
"""

from __future__ import annotations

import glob
import os
import re
import subprocess
import tempfile
from urllib.parse import parse_qs, urlparse


class TranscriptError(RuntimeError):
    pass


# --- URL / id ----------------------------------------------------------------
def extract_video_id(url_or_id: str) -> str:
    """Accept a full YouTube URL (watch, youtu.be, embed, shorts) or a bare id."""
    s = url_or_id.strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", s):
        return s
    parsed = urlparse(s)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    if host == "youtu.be":
        vid = parsed.path.lstrip("/").split("/")[0]
    elif host in ("youtube.com", "m.youtube.com", "music.youtube.com"):
        if parsed.path == "/watch":
            vid = parse_qs(parsed.query).get("v", [""])[0]
        elif parsed.path.startswith(("/embed/", "/shorts/", "/v/", "/live/")):
            vid = parsed.path.split("/")[2]
        else:
            vid = ""
    else:
        vid = ""
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", vid):
        raise TranscriptError(f"Could not extract a YouTube video id from {url_or_id!r}")
    return vid


# --- Fetch -------------------------------------------------------------------
def fetch_transcript(video_id: str, languages: list[str] | None = None) -> list[dict]:
    """Return a normalized transcript, trying the API first, then yt-dlp."""
    languages = languages or ["en", "en-US", "en-GB"]
    try:
        segs = _via_api(video_id, languages)
        if segs:
            return segs
    except Exception:  # noqa: BLE001 - fall through to yt-dlp on any API failure
        pass
    try:
        segs = _via_ytdlp(video_id, languages)
        if segs:
            return segs
    except Exception:  # noqa: BLE001
        pass
    raise TranscriptError(
        f"No transcript available for video {video_id!r}. "
        "The video may have captions disabled. "
        "TODO: fall back to Whisper transcription of the audio."
    )


def _via_api(video_id: str, languages: list[str]) -> list[dict]:
    from youtube_transcript_api import YouTubeTranscriptApi

    # youtube-transcript-api changed its surface across versions; support both.
    raw = None
    if hasattr(YouTubeTranscriptApi, "get_transcript"):  # <= 0.6.x
        raw = YouTubeTranscriptApi.get_transcript(video_id, languages=languages)
    else:  # >= 1.0
        fetched = YouTubeTranscriptApi().fetch(video_id, languages=languages)
        raw = fetched.to_raw_data() if hasattr(fetched, "to_raw_data") else list(fetched)
    return _normalize(raw)


def _normalize(raw) -> list[dict]:
    out = []
    for item in raw:
        if isinstance(item, dict):
            text, start, dur = item.get("text", ""), item.get("start", 0.0), item.get("duration", 0.0)
        else:  # object with attributes (newer API)
            text = getattr(item, "text", "")
            start = getattr(item, "start", 0.0)
            dur = getattr(item, "duration", 0.0)
        text = " ".join(str(text).split())
        if text:
            out.append({"text": text, "start": float(start), "duration": float(dur)})
    return out


# --- yt-dlp VTT fallback -----------------------------------------------------
def _via_ytdlp(video_id: str, languages: list[str]) -> list[dict]:
    with tempfile.TemporaryDirectory() as tmp:
        out_tmpl = os.path.join(tmp, "%(id)s")
        cmd = [
            "yt-dlp", "--skip-download", "--write-auto-subs", "--write-subs",
            "--sub-langs", ",".join(languages) + ",en.*",
            "--sub-format", "vtt", "-o", out_tmpl,
            f"https://www.youtube.com/watch?v={video_id}",
        ]
        subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=120)
        vtts = sorted(glob.glob(os.path.join(tmp, "*.vtt")))
        if not vtts:
            return []
        with open(vtts[0], encoding="utf-8") as fh:
            return _parse_vtt(fh.read())


_TS = re.compile(r"(\d{1,2}):(\d{2}):(\d{2})[.,](\d{3})\s*-->\s*(\d{1,2}):(\d{2}):(\d{2})[.,](\d{3})")
_TAG = re.compile(r"<[^>]+>")


def _parse_vtt(content: str) -> list[dict]:
    def to_sec(h, m, s, ms):
        return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0

    segs: list[dict] = []
    seen: set[tuple] = set()
    lines = content.splitlines()
    i = 0
    while i < len(lines):
        m = _TS.search(lines[i])
        if not m:
            i += 1
            continue
        start = to_sec(*m.groups()[:4])
        end = to_sec(*m.groups()[4:])
        i += 1
        parts = []
        while i < len(lines) and lines[i].strip() and not _TS.search(lines[i]):
            parts.append(_TAG.sub("", lines[i]))
            i += 1
        text = " ".join(" ".join(parts).split())
        key = (round(start, 1), text)
        if text and key not in seen:  # auto-subs repeat rolling lines; de-dupe
            seen.add(key)
            segs.append({"text": text, "start": start, "duration": max(0.0, end - start)})
    return segs


# --- Helpers -----------------------------------------------------------------
def transcript_duration(transcript: list[dict]) -> float:
    """Best-effort source duration from the last caption's end time."""
    if not transcript:
        return 0.0
    last = transcript[-1]
    return round(last["start"] + last["duration"], 3)
