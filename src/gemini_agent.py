from __future__ import annotations

import argparse
import json
import os
from logging import getLogger
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional

from google import genai
from google.genai import types
from google.genai import errors as genai_errors
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception

from config import settings

logger = getLogger(__name__)



from tools import (
    TEXT_VERIFIER_SPEC,
    TEXT_VERIFIER_TOOL_NAME,
    run_text_verifier_tool,
    FORM_FILLER_SPEC,
    FORM_FILLER_TOOL_NAME,
    run_form_filler_tool,
)
from src.loader import PageLoader


DEFAULT_MODEL = settings.gemini.model
DEFAULT_MAX_STEPS = settings.gemini.max_steps


def _is_transient_gemini_error(exc: BaseException) -> bool:
    """Return True for Gemini errors worth retrying (rate-limit, server errors)."""
    if isinstance(exc, genai_errors.APIError):
        code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
        if code in (429, 500, 502, 503, 504):
            return True
    return False


_gemini_retry = retry(
    retry=retry_if_exception(_is_transient_gemini_error),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    stop=stop_after_attempt(4),
    reraise=True,
)


_PROMPTS_DIR = Path(__file__).parent / "prompts"

def _load_prompt(name: str) -> str:
    path = _PROMPTS_DIR / name
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    logger.warning(f"Prompt file not found: {path}")
    return ""

SYSTEM_INSTRUCTION = _load_prompt("system_instruction.txt")


def _build_tools() -> List[types.Tool]:
    text_decl = types.FunctionDeclaration(
        name=TEXT_VERIFIER_SPEC["name"],
        description=TEXT_VERIFIER_SPEC["description"],
        parametersJsonSchema=TEXT_VERIFIER_SPEC["parameters"],
    )
    form_decl = types.FunctionDeclaration(
        name=FORM_FILLER_SPEC["name"],
        description=FORM_FILLER_SPEC["description"],
        parametersJsonSchema=FORM_FILLER_SPEC["parameters"],
    )
    return [types.Tool(functionDeclarations=[text_decl, form_decl])]


def _extract_text_and_calls(
    response: types.GenerateContentResponse,
) -> Tuple[str, List[types.FunctionCall], types.Content]:
    candidate = (response.candidates or [None])[0]
    if candidate is None or candidate.content is None:
        return "", [], types.Content(parts=[], role="model")

    content = candidate.content
    parts = content.parts or []

    text_chunks: List[str] = []
    calls: List[types.FunctionCall] = []

    for part in parts:
        if part.text:
            text_chunks.append(part.text)
        if part.function_call:
            calls.append(part.function_call)

    return "".join(text_chunks).strip(), calls, content


def _run_tool_call(call: types.FunctionCall, loader: Optional[PageLoader] = None) -> Dict[str, Any]:
    args = call.args or {}
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            return {"error": "Invalid tool arguments (not JSON)."}

    return _run_tool_by_name(call.name, args, loader)


def _run_tool_by_name(
    name: str, args: Dict[str, Any], loader: Optional[PageLoader] = None
) -> Dict[str, Any]:
    """Run a tool by name and args; used by both Gemini and OpenAI agents."""
    if name == TEXT_VERIFIER_TOOL_NAME:
        return run_text_verifier_tool(args)
    if name == FORM_FILLER_TOOL_NAME:
        return run_form_filler_tool(args, loader=loader)
    return {"error": f"Unknown tool: {name}"}


def _openai_tools() -> List[Dict[str, Any]]:
    """Tool definitions in OpenAI chat completions format."""
    return [
        {
            "type": "function",
            "function": {
                "name": TEXT_VERIFIER_SPEC["name"],
                "description": TEXT_VERIFIER_SPEC["description"],
                "parameters": TEXT_VERIFIER_SPEC["parameters"],
            },
        },
        {
            "type": "function",
            "function": {
                "name": FORM_FILLER_SPEC["name"],
                "description": FORM_FILLER_SPEC["description"],
                "parameters": FORM_FILLER_SPEC["parameters"],
            },
        },
    ]


class GeminiAgent:
    def __init__(self, api_key: str, model: str = DEFAULT_MODEL, loader: Optional[PageLoader] = None):
        self.client = genai.Client(api_key=api_key)
        self.model = model
        self.loader = loader
        self.tools = _build_tools()
        self.total_tokens_used: int = 0

    def _track_usage(self, response):
        """Accumulate token counts from the response metadata."""
        meta = getattr(response, "usage_metadata", None)
        if meta:
            prompt = getattr(meta, "prompt_token_count", 0) or 0
            candidates = getattr(meta, "candidates_token_count", 0) or 0
            self.total_tokens_used += prompt + candidates

    def run(self, task: str, max_steps: Optional[int] = DEFAULT_MAX_STEPS) -> str:
        history: List[types.Content] = [
            types.Content(role="user", parts=[types.Part(text=task)])
        ]

        config = types.GenerateContentConfig(
            systemInstruction=SYSTEM_INSTRUCTION,
            tools=self.tools,
        )

        try:
            step = 0
            while True:
                if max_steps is not None and step >= max_steps:
                    return "Stopped: reached max tool steps without a final answer."
                step += 1

                response = _gemini_retry(self.client.models.generate_content)(
                    model=self.model,
                    contents=history,
                    config=config,
                )
                self._track_usage(response)

                text, calls, model_content = _extract_text_and_calls(response)
                history.append(model_content)

                if not calls:
                    return text or "No response generated."

                for call in calls:
                    result = _run_tool_call(call, loader=self.loader)
                    history.append(
                        types.Content(
                            role="tool",
                            parts=[
                                types.Part(
                                    functionResponse=types.FunctionResponse(
                                        name=call.name,
                                        response=result,
                                    )
                                )
                            ],
                        )
                    )
        except Exception as exc:
            logger.error(f"Gemini agent execution failed: {exc}")
            return f"Agent Error: {str(exc)}"


class OpenAIAgent:
    """Agent using OpenAI chat completions with tool-calling; same interface as GeminiAgent."""

    def __init__(
        self,
        api_key: str,
        model: str | None = None,
        loader: Optional[PageLoader] = None,
    ):
        from openai import OpenAI
        self.client = OpenAI(api_key=api_key)
        self.model = model or settings.openai.model
        self.loader = loader
        self.openai_tools = _openai_tools()
        self.total_tokens_used: int = 0

    def run(self, task: str, max_steps: Optional[int] = DEFAULT_MAX_STEPS) -> str:
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_INSTRUCTION},
            {"role": "user", "content": task},
        ]
        step = 0
        try:
            while True:
                if max_steps is not None and step >= max_steps:
                    return "Stopped: reached max tool steps without a final answer."
                step += 1

                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=self.openai_tools,
                )
                msg = response.choices and response.choices[0] and response.choices[0].message
                if not msg:
                    return "No response from model."

                usage = getattr(response, "usage", None)
                if usage:
                    self.total_tokens_used += (getattr(usage, "prompt_tokens", 0) or 0) + (
                        getattr(usage, "completion_tokens", 0) or 0
                    )

                if not getattr(msg, "tool_calls", None):
                    return (msg.content or "").strip() or "No response generated."

                # Append assistant message with tool_calls
                messages.append({
                    "role": "assistant",
                    "content": msg.content or None,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                        }
                        for tc in msg.tool_calls
                    ],
                })

                for tc in msg.tool_calls:
                    name = tc.function.name
                    try:
                        args = json.loads(tc.function.arguments or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    result = _run_tool_by_name(name, args, self.loader)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    })
        except Exception as exc:
            logger.error("OpenAI agent execution failed: %s", exc)
            return f"Agent Error: {str(exc)}"


def get_agent(
    loader: Optional[PageLoader] = None,
    prefer_gemini: bool = True,
):
    """Return an agent: prefer Gemini if key exists, else OpenAI. Returns None if no key is set."""
    if prefer_gemini and (settings.gemini.api_key or "").strip():
        return GeminiAgent(
            api_key=settings.gemini.api_key,
            model=settings.gemini.model,
            loader=loader,
        )
    if (settings.openai.api_key or "").strip():
        return OpenAIAgent(
            api_key=settings.openai.api_key,
            model=settings.openai.model,
            loader=loader,
        )
    if not prefer_gemini and (settings.gemini.api_key or "").strip():
        return GeminiAgent(
            api_key=settings.gemini.api_key,
            model=settings.gemini.model,
            loader=loader,
        )
    return None


def run_agent_with_fallback(
    task: str,
    loader: Optional[PageLoader] = None,
    max_steps: Optional[int] = DEFAULT_MAX_STEPS,
):
    """Run agent with Gemini first; on failure, retry with OpenAI if available."""
    agent = get_agent(loader=loader, prefer_gemini=True)
    if not agent:
        raise RuntimeError(
            "No LLM API key. Set GEMINI_API_KEY and/or OPENAI_API_KEY in the environment."
        )
    try:
        return agent.run(task=task, max_steps=max_steps)
    except Exception as exc:
        logger.warning("Primary agent failed (%s), trying fallback: %s", type(agent).__name__, exc)
        fallback = get_agent(loader=loader, prefer_gemini=not isinstance(agent, GeminiAgent))
        if fallback is not None and type(fallback) != type(agent):
            return fallback.run(task=task, max_steps=max_steps)
        raise


def run_from_payload(api_key: str, model: str, payload: Dict[str, Any]) -> str:
    url_report = payload.get("url_report")
    layout_report = payload.get("layout_report")
    visible_text = payload.get("visible_text") or ""

    text_report = run_text_verifier_tool({"visible_text": visible_text})
    if isinstance(text_report, dict) and text_report.get("error"):
        return (
            "Text verification failed: "
            f"{text_report.get('error')} "
            f"{text_report.get('details', '')}".strip()
        )

    prompt = (
        "You are a web QA agent. Generate a concise final report based only on the data provided.\n"
        "Return STRICT JSON with these fields:\n"
        "{\n"
        '  "status": "PASS | WARNING | FAIL",\n'
        '  "url_verification": "short summary",\n'
        '  "layout_validation": "short summary",\n'
        '  "text_verification": "short summary",\n'
        '  "notes": "1-2 factual sentences"\n'
        "}\n\n"
        "URL report:\n"
        f"{json.dumps(url_report, ensure_ascii=False)}\n\n"
        "Layout report:\n"
        f"{json.dumps(layout_report, ensure_ascii=False)}\n\n"
        "Text report:\n"
        f"{json.dumps(text_report, ensure_ascii=False)}\n"
    )

    from src.llm_client import generate_text_simple
    return generate_text_simple(
        prompt,
        model_gemini=model or None,
        model_openai=None,
        json_mode=True,
    )


def run_from_agent_payload(
    api_key: str, model: str, payload_path: str
) -> str:
    try:
        with open(payload_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as exc:
        return f"Failed to read payload JSON: {exc}"

    return run_from_payload(api_key=api_key, model=model, payload=payload)


def _get_api_key() -> str:
    """Preferred API key (Gemini first, then OpenAI) for CLI compatibility."""
    if (settings.gemini.api_key or "").strip():
        return settings.gemini.api_key
    if (settings.openai.api_key or "").strip():
        return settings.openai.api_key
    return ""


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run QA agent (Gemini by default, falls back to OpenAI if needed)."
    )
    parser.add_argument("--task", required=True, help="User task or prompt.")
    parser.add_argument(
        "--agent-input-json",
        help="Path to pipeline payload JSON with url_report, layout_report, visible_text.",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help="Model name for report generation (Gemini or OpenAI from config).",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=DEFAULT_MAX_STEPS,
        help="Maximum tool/think steps.",
    )

    args = parser.parse_args()
    api_key = _get_api_key()
    if not api_key and not (settings.gemini.api_key or settings.openai.api_key):
        raise SystemExit(
            "Missing API key. Set GEMINI_API_KEY and/or OPENAI_API_KEY in the environment."
        )

    if args.agent_input_json:
        answer = run_from_agent_payload(
            api_key=api_key or settings.gemini.api_key or settings.openai.api_key,
            model=args.model,
            payload_path=args.agent_input_json,
        )
    else:
        agent = get_agent(loader=None, prefer_gemini=True)
        if not agent:
            raise SystemExit(
                "Missing API key. Set GEMINI_API_KEY and/or OPENAI_API_KEY in the environment."
            )
        answer = agent.run(task=args.task, max_steps=args.max_steps)
    print(answer)


if __name__ == "__main__":
    main()
