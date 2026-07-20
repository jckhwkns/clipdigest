"""Swappable LLM client that returns parsed JSON.

Supports Anthropic and OpenAI. The provider is chosen from the environment so
the rest of the pipeline never needs to care which one is in use:

    CLIPDIGEST_PROVIDER   "anthropic" | "openai"   (auto-detected if unset)
    CLIPDIGEST_MODEL      model id override
    ANTHROPIC_API_KEY / OPENAI_API_KEY

Both SDKs are imported lazily so the package imports fine with only one (or,
for `--help`, neither) installed.
"""

from __future__ import annotations

import json
import os
import re

from . import config


class LLMError(RuntimeError):
    pass


def _detect_provider() -> str:
    explicit = os.environ.get("CLIPDIGEST_PROVIDER", "").strip().lower()
    if explicit in ("anthropic", "openai"):
        return explicit
    if explicit:
        raise LLMError(f"Unknown CLIPDIGEST_PROVIDER={explicit!r} (use 'anthropic' or 'openai')")
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    raise LLMError(
        "No LLM API key found. Set ANTHROPIC_API_KEY or OPENAI_API_KEY "
        "(and optionally CLIPDIGEST_PROVIDER / CLIPDIGEST_MODEL)."
    )


class LLMClient:
    """Thin wrapper exposing a single `.json()` call with a strict-retry."""

    def __init__(self, provider: str | None = None, model: str | None = None):
        self.provider = provider or _detect_provider()
        env_model = os.environ.get("CLIPDIGEST_MODEL")
        if self.provider == "anthropic":
            self.model = model or env_model or config.DEFAULT_ANTHROPIC_MODEL
        else:
            self.model = model or env_model or config.DEFAULT_OPENAI_MODEL

    # -- public ---------------------------------------------------------------
    def json(self, system: str, user: str) -> dict | list:
        """Return the model's reply parsed as JSON.

        On malformed JSON, retry once with a stricter nudge before giving up.
        """
        raw = self._complete(system, user)
        try:
            return _extract_json(raw)
        except ValueError:
            strict = (
                user
                + "\n\nYOUR PREVIOUS REPLY WAS NOT VALID JSON. "
                "Reply with ONLY a single JSON value. No prose, no markdown fences."
            )
            raw = self._complete(system, strict)
            try:
                return _extract_json(raw)
            except ValueError as exc:
                raise LLMError(f"Model did not return valid JSON:\n{raw[:500]}") from exc

    # -- providers ------------------------------------------------------------
    def _complete(self, system: str, user: str) -> str:
        if self.provider == "anthropic":
            return self._anthropic(system, user)
        return self._openai(system, user)

    def _anthropic(self, system: str, user: str) -> str:
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover
            raise LLMError("The 'anthropic' package is required. pip install anthropic") from exc
        client = anthropic.Anthropic()
        msg = client.messages.create(
            model=self.model,
            max_tokens=config.LLM_MAX_TOKENS,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(block.text for block in msg.content if getattr(block, "type", None) == "text")

    def _openai(self, system: str, user: str) -> str:
        try:
            import openai
        except ImportError as exc:  # pragma: no cover
            raise LLMError("The 'openai' package is required. pip install openai") from exc
        client = openai.OpenAI()
        resp = client.chat.completions.create(
            model=self.model,
            max_tokens=config.LLM_MAX_TOKENS,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return resp.choices[0].message.content or ""


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def _extract_json(raw: str) -> dict | list:
    """Parse JSON from a model reply, tolerating fences and surrounding prose."""
    text = _FENCE.sub("", raw).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Fall back to the first balanced {...} or [...] span.
    start = min([i for i in (text.find("{"), text.find("[")) if i != -1], default=-1)
    if start == -1:
        raise ValueError("no JSON found")
    opener = text[start]
    closer = "}" if opener == "{" else "]"
    depth, in_str, esc = 0, False, False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return json.loads(text[start : i + 1])
    raise ValueError("unbalanced JSON")
