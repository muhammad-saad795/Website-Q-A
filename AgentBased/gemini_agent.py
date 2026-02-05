"""
Minimal Gemini tool-using agent.

Usage:
  python -m AgentBased.gemini_agent --task "Verify https://example.com"
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any, Dict, List, Tuple

from google import genai
from google.genai import types

from tools import (
    TEXT_VERIFIER_SPEC,
    TEXT_VERIFIER_TOOL_NAME,
    run_text_verifier_tool,
)


DEFAULT_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
DEFAULT_MAX_STEPS = 5


SYSTEM_INSTRUCTION = (
    "You are a practical, tool-using web QA agent. "
    "Decide when a tool is needed, call it, and then provide a concise final answer. "
    "Do not reveal hidden reasoning. If a tool call fails, explain it briefly and proceed."
)


def _build_tools() -> List[types.Tool]:
    declaration = types.FunctionDeclaration(
        name=TEXT_VERIFIER_SPEC["name"],
        description=TEXT_VERIFIER_SPEC["description"],
        parametersJsonSchema=TEXT_VERIFIER_SPEC["parameters"],
    )
    return [types.Tool(functionDeclarations=[declaration])]


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


def _run_tool_call(call: types.FunctionCall) -> Dict[str, Any]:
    if call.name != TEXT_VERIFIER_TOOL_NAME:
        return {"error": f"Unknown tool: {call.name}"}

    args = call.args or {}
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            return {"error": "Invalid tool arguments (not JSON)."}

    return run_text_verifier_tool(args)


class GeminiAgent:
    def __init__(self, api_key: str, model: str = DEFAULT_MODEL):
        self.client = genai.Client(api_key=api_key)
        self.model = model
        self.tools = _build_tools()

    def run(self, task: str, max_steps: int = DEFAULT_MAX_STEPS) -> str:
        history: List[types.Content] = [
            types.Content(role="user", parts=[types.Part(text=task)])
        ]

        config = types.GenerateContentConfig(
            systemInstruction=SYSTEM_INSTRUCTION,
            tools=self.tools,
        )

        for _ in range(max_steps):
            response = self.client.models.generate_content(
                model=self.model,
                contents=history,
                config=config,
            )

            text, calls, model_content = _extract_text_and_calls(response)
            history.append(model_content)

            if not calls:
                return text or "No response generated."

            for call in calls:
                result = _run_tool_call(call)
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

        return "Stopped: reached max tool steps without a final answer."


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

    client = genai.Client(api_key=api_key)
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

    response = client.models.generate_content(
        model=model,
        contents=prompt,
    )
    text, _, _ = _extract_text_and_calls(response)
    return text or "No response generated."


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
    return (
        os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
        or ""
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Gemini tool-using agent.")
    parser.add_argument("--task", required=True, help="User task or prompt.")
    parser.add_argument(
        "--agent-input-json",
        help="Path to pipeline payload JSON with url_report, layout_report, visible_text.",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help="Gemini model name (default from GEMINI_MODEL or gemini-2.0-flash).",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=DEFAULT_MAX_STEPS,
        help="Maximum tool/think steps.",
    )

    args = parser.parse_args()
    api_key = _get_api_key()
    if not api_key:
        raise SystemExit(
            "Missing API key. Set GEMINI_API_KEY or GOOGLE_API_KEY in the environment."
        )

    if args.agent_input_json:
        answer = run_from_agent_payload(
            api_key=api_key, model=args.model, payload_path=args.agent_input_json
        )
    else:
        agent = GeminiAgent(api_key=api_key, model=args.model)
        answer = agent.run(task=args.task, max_steps=args.max_steps)
    print(answer)


if __name__ == "__main__":
    main()
