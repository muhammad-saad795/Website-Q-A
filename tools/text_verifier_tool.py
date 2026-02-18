"""
Gemini tool: text_verifier

Uses Gemini to evaluate whether visible page text matches the intended page type.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict

from google import genai
from google.genai import types
from google.genai import errors as genai_errors



TOOL_NAME = "text_verifier"

TEXT_ANALYSIS_PROMPT = """
You are a website content evaluator.

Your ONLY task:
Determine whether the visible page text MATCHES what the page is supposed to say.

Step 1 — Infer the page's intended purpose
- Use headings, labels, and dominant keywords only.
- Examples: registration page, login page, landing page, documentation, blog, pricing page.

Step 2 — Evaluate content alignment
Check whether the text:
- Contains the expected information for that page type
- Avoids unrelated or contradictory content
- Is not placeholder, demo, or filler text

OUTPUT FORMAT (STRICT JSON ONLY):

{{
  "status": "PASS | FAIL",
  "inferred_page_type": "short label",
  "alignment": "MATCH | PARTIAL_MATCH | MISMATCH",
  "reason": "1–2 factual sentences explaining the decision"
}}

RULES:
- Do NOT evaluate grammar, UX, or design unless it directly affects alignment.
- Do NOT suggest fixes.
- Do NOT assume missing content.
- Be concise.
- No markdown.
- No extra fields.

Visible page text:
{visible_text}
"""


GEMINI_TOOL_SPEC: Dict[str, Any] = {
    "name": TOOL_NAME,
    "description": (
        "Evaluate visible page text to decide if it matches the page's intended purpose. "
        "Returns strict JSON with status, inferred page type, alignment, and reason."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "visible_text": {
                "type": "string",
                "description": "Visible page text to verify.",
            },
            "model": {
                "type": "string",
                "description": "Optional Gemini model override.",
            },
        },
        "required": ["visible_text"],
    },
}


def _get_api_key() -> str:
    return settings.gemini.api_key


def _call_gemini(visible_text: str, model: str | None = None) -> Dict[str, Any]:
    api_key = _get_api_key()
    if not api_key:
        return {"error": "Missing API key. Set GEMINI_API_KEY or GOOGLE_API_KEY."}

    client = genai.Client(api_key=api_key)
    prompt = TEXT_ANALYSIS_PROMPT.format(visible_text=visible_text.strip())
    used_model = model or os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

    try:
        response = client.models.generate_content(
            model=used_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                responseMimeType="application/json",
            ),
        )
    except genai_errors.APIError as exc:
        return {
            "error": "Gemini API error",
            "details": str(exc),
        }
    except Exception as exc:
        return {
            "error": "Unexpected error calling Gemini",
            "details": str(exc),
        }

    candidate = (response.candidates or [None])[0]
    if candidate is None or candidate.content is None:
        return {"error": "No response from model."}

    parts = candidate.content.parts or []
    text = "".join([p.text for p in parts if p.text]).strip()
    if not text:
        return {"error": "Empty model response."}

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Best-effort fallback: return raw text for debugging.
        return {"error": "Model returned non-JSON output.", "raw": text}


def run_text_verifier_tool(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Runtime wrapper for the Gemini tool.

    Args:
        args: Tool arguments matching GEMINI_TOOL_SPEC["parameters"].
    """
    if not isinstance(args, dict):
        return {"error": "Invalid arguments: expected an object."}

    visible_text = args.get("visible_text")
    if not isinstance(visible_text, str) or not visible_text.strip():
        return {"error": "Missing or invalid 'visible_text'."}

    model = args.get("model")
    return _call_gemini(visible_text=visible_text, model=model)


__all__ = [
    "TOOL_NAME",
    "GEMINI_TOOL_SPEC",
    "TEXT_ANALYSIS_PROMPT",
    "run_text_verifier_tool",
]
