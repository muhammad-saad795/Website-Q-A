"""
Unified LLM client: Gemini by default, OpenAI as fallback when key is missing or calls fail.
Used for simple text generation (no tools): text verifier, master report.
"""

from __future__ import annotations

import json
from logging import getLogger

from config import settings

logger = getLogger(__name__)


def _try_gemini_text(prompt: str, *, model: str | None = None, json_mode: bool = False) -> str | None:
    """Return generated text or None on failure."""
    api_key = (settings.gemini.api_key or "").strip()
    if not api_key:
        return None
    model = model or settings.gemini.model
    try:
        from google import genai
        from google.genai import types
        from google.genai import errors as genai_errors

        client = genai.Client(api_key=api_key)
        config = types.GenerateContentConfig(
            responseMimeType="application/json" if json_mode else None,
        )
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=config,
        )
        candidate = (response.candidates or [None])[0]
        if candidate is None or candidate.content is None:
            return None
        parts = candidate.content.parts or []
        text = "".join([p.text or "" for p in parts]).strip()
        return text or None
    except Exception as exc:
        logger.warning("Gemini text generation failed: %s", exc)
        return None


def _try_openai_text(prompt: str, *, model: str | None = None, json_mode: bool = False) -> str | None:
    """Return generated text or None on failure."""
    api_key = (settings.openai.api_key or "").strip()
    if not api_key:
        return None
    model = model or settings.openai.model
    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        kwargs = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        response = client.chat.completions.create(**kwargs)
        choice = response.choices and response.choices[0]
        if not choice or not choice.message or not choice.message.content:
            return None
        return choice.message.content.strip()
    except Exception as exc:
        logger.warning("OpenAI text generation failed: %s", exc)
        return None


def generate_text_simple(
    prompt: str,
    *,
    model_gemini: str | None = None,
    model_openai: str | None = None,
    json_mode: bool = False,
) -> str:
    """
    Generate text using Gemini first; if key is missing or the call fails, use OpenAI.
    Raises RuntimeError if both are unavailable or both fail.
    """
    # Prefer Gemini when key exists
    if (settings.gemini.api_key or "").strip():
        out = _try_gemini_text(prompt, model=model_gemini, json_mode=json_mode)
        if out is not None:
            return out
    # Fallback to OpenAI
    if (settings.openai.api_key or "").strip():
        out = _try_openai_text(prompt, model=model_openai, json_mode=json_mode)
        if out is not None:
            return out
    raise RuntimeError(
        "No LLM available. Set GEMINI_API_KEY and/or OPENAI_API_KEY in the environment."
    )
