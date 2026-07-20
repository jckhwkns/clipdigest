# clipdigest

Turn a long YouTube video into a **comprehensible condensed viewer** — a static
web page that plays only the worthwhile segments back-to-back, edited down to a
target length by an LLM "editor."

It **never downloads or re-hosts** the video. It drives YouTube's own embedded
IFrame player and seeks from one kept segment to the next in the browser — a
"virtual edit" streaming the real video with no file. The whole edit is a small
JSON manifest; the page is a static viewer over it.

**The distinguishing feature:** it preserves comprehension across cuts. When a
kept segment references something only established in a dropped segment, it
bridges the gap — either by pulling a short setup slice back in, or by showing an
on-screen overlay card timed just before the reference lands.

## Install

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# or:  pip install -e .
```

Requires Python 3.11+.

## API key

clipdigest uses an LLM as the editor. Set **one** of:

```bash
export OPENAI_API_KEY=sk-...            # uses OpenAI  (default model: gpt-4o-mini)
export ANTHROPIC_API_KEY=sk-ant-...     # uses Anthropic (default model: claude-sonnet-5)
```

If both are set, Anthropic wins unless you force a provider. The OpenAI default
is **`gpt-4o-mini`** — the cheap option, and fine for this JSON task. Bump to
`gpt-4o` only if you want sharper edits:

```bash
export CLIPDIGEST_PROVIDER=openai       # force a provider ("openai" | "anthropic")
export CLIPDIGEST_MODEL=gpt-4o          # model id override (quality > cost)
```

> **Cost note:** a one-hour video is roughly 12–18k transcript tokens, sent
> twice (selection + comprehension). On `gpt-4o-mini` that's a fraction of a
> cent per run; on `gpt-4o`, low single-digit cents. There is no free tier —
> `gpt-4o-mini` is the cheapest sensible choice.

## Usage

```bash
clipdigest <youtube_url> --minutes 12 [--focus "the funding history and the pivot"] [--out ./output]
```

- `--minutes` (required): target duration of the condensed cut.
- `--focus` (optional): free-text steer. If omitted, it selects on what's most
  substantive on its own.
- `--out` (optional): output directory (default `./output`).

Writes `manifest.json` + `index.html`. Open `index.html` in a browser and click
**Play** (one click is required — browsers block autoplay).

### Examples

```bash
# A talk condensed to ~12 minutes, keeping the narrative coherent
clipdigest "https://www.youtube.com/watch?v=VIDEO_ID" --minutes 12

# Steer the edit toward a theme
clipdigest "https://youtu.be/VIDEO_ID" --minutes 8 \
  --focus "the funding history and the pivot" --out ./digest

# Run as a module (no install)
python -m clipdigest "VIDEO_ID" --minutes 10
```

## How it works

1. **Transcript** — `youtube-transcript-api` (primary; no download). Falls back to
   parsing `yt-dlp` auto-sub VTT. No transcript → clear error (Whisper is a TODO).
2. **Segment selection (LLM)** — full timestamped transcript + target + focus →
   ordered clips with a short reason each. Aims *under* target so padding fits.
3. **Comprehension resolution (LLM)** — a second pass over the selected clips
   *and* the full transcript finds dangling references (referential, definitional,
   causal, setup–payoff, numeric) and resolves each as a `pull_in` (re-include
   setup) or a `bridge` (one-line overlay). Also emits a global `primer`.
4. **Pad, merge, budget** — clips are padded (−1.5s / +1.0s), overlaps merged,
   and if the cut runs >10% over target the lowest-value clips are trimmed.
5. **Manifest** — `manifest.json` with the padded segments (original time),
   primer, and bridges (translated to the condensed timeline) + stats.
6. **Viewer** — a self-contained `index.html` (vanilla JS + IFrame Player API):
   self-advancing playback, primer + inline bridge cards (with optional pause),
   an interactive segment list (click to jump, "open on YouTube" links), stats,
   and a "You may have missed" section.

The manifest is embedded inline in `index.html`, so it works from `file://` with
no server; `manifest.json` is also written separately so the edit can be shared.

## Configuration

All tunables (padding, under-target ratio, poll rate, card timing / reading
speed, model defaults) live at the top of [`clipdigest/config.py`](clipdigest/config.py).

## Notes & limits

- Primary path never downloads video, staying cleanly within YouTube's terms.
- Needs a video that has captions. Auto-generated captions work.
- An offline burned-in export (yt-dlp + ffmpeg) is intentionally **not** built —
  that's the ToS-heavy path and would be isolated behind a separate flag if added.
