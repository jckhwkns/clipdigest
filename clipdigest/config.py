"""Tunable constants for the clipdigest pipeline and viewer.

Everything a person might reasonably want to tweak lives here so the rest of
the code reads cleanly and the behaviour is easy to reason about.
"""

# --- Padding (seconds) -------------------------------------------------------
# Kept clips are padded so cuts don't land mid-breath. Padding adds time back,
# which is why selection aims *under* the target (see UNDER_TARGET_RATIO).
PAD_START = 1.5  # seconds of lead-in added before each clip
PAD_END = 1.0    # seconds of tail added after each clip

# --- Budget ------------------------------------------------------------------
# Ask the LLM to select clips summing to ~85% of target; padding fills the rest.
UNDER_TARGET_RATIO = 0.85
# If the padded/merged cut exceeds target by more than this fraction, trim the
# lowest-value clips until we're back under the ceiling.
OVER_TARGET_TOLERANCE = 0.10

# --- Viewer timing -----------------------------------------------------------
POLL_HZ = 4                 # times/sec the player checks whether to hop segments
PRIMER_SECONDS = 12.0       # how long the primer card stays up (condensed time)
CARD_LEAD_SECONDS = 1.0     # show a bridge card this long BEFORE its anchor
CARD_MIN_SECONDS = 2.5      # minimum time any bridge card stays up
READING_SPEED_WPS = 2.5     # words/sec used to size a card's hold time
PAUSE_HOLD_SECONDS = 2.5    # how long a `pause` bridge holds the video paused

# --- LLM defaults (overridable via env) -------------------------------------
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-5"
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"  # cheap default; override w/ CLIPDIGEST_MODEL=gpt-4o for quality
LLM_MAX_TOKENS = 8000
