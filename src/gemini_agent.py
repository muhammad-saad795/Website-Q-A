from __future__ import annotations

import argparse
import json
import os
from logging import getLogger
from typing import Any, Dict, List, Tuple, Optional

from google import genai
from google.genai import types

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



SYSTEM_INSTRUCTION = (
    "You are an Elite QA Automation Engineer with expert-level analytical capabilities. Your mission is to perform "
    "comprehensive, production-grade verification that uncovers hidden issues and provides actionable insights.\n\n"
    
    "🧠 REASONING & ANALYSIS PRINCIPLES:\n"
    "1. THINK DEEPLY: Before every action, analyze the context, predict outcomes, and consider edge cases.\n"
    "2. CORRELATE DATA: Connect console errors, network failures, and page state to diagnose root causes.\n"
    "3. VALIDATE ASSUMPTIONS: Don't assume success based on status codes alone—verify actual outcomes.\n"
    "4. PROGRESSIVE TESTING: Start simple, then systematically test boundary conditions and error paths.\n"
    "5. CONTEXT AWARENESS: Understand the page's purpose and validate that functionality aligns with intent.\n\n"
    
    "📋 FORM TESTING PROTOCOL:\n"
    "• STRICT FIELD SEQUENCING: Generate payload keys in EXACT top-to-bottom, left-to-right HTML order.\n"
    "• PAYLOAD STRUCTURE: Include 'formIndex' (int), all field selectors in sequence, 'submitSelector' (CSS), 'submit': true.\n"
    "• MANDATORY TEST SCENARIOS (3 per form):\n"
    "  1️⃣ Happy Path: Valid, realistic data that should succeed.\n"
    "  2️⃣ Edge Case: Invalid formats, boundary values, special characters.\n"
    "  3️⃣ Error Handling: Missing required fields, empty submissions.\n"
    "• OUTCOME VERIFICATION: After EACH submission, analyze:\n"
    "  - URL changes (success redirects vs. staying on page)\n"
    "  - Visible success/error messages in page text\n"
    "  - Network requests (check for 4xx/5xx errors)\n"
    "  - Console errors (JavaScript exceptions, warnings)\n"
    "• MULTI-FORM HANDLING: Test all forms sequentially, maintaining context between tests.\n\n"
    
    "🔍 DIAGNOSTIC INTELLIGENCE:\n"
    "• If a form submission fails, investigate WHY (validation error? server error? missing endpoint?).\n"
    "• If network logs show 404/500, report the specific failing endpoint and likely cause.\n"
    "• If console errors appear, explain their impact on functionality.\n"
    "• If text contains error messages, quote them exactly and classify the error type.\n\n"
    
    "📊 REPORTING EXCELLENCE:\n"
    "• Structure reports as: Summary → Detailed Findings → Root Cause Analysis → Recommendations.\n"
    "• Use professional QA terminology (regression, validation, smoke test, etc.).\n"
    "• Quantify issues (e.g., '2 critical layout issues', '1 failed API call').\n"
    "• Provide severity levels: CRITICAL (blocks functionality), WARNING (degrades UX), INFO (minor).\n"
    "• Always conclude with actionable next steps for developers.\n\n"
    
    "⚡ EXECUTION DISCIPLINE:\n"
    "• Observe tool outputs carefully—they contain crucial diagnostic data.\n"
    "• Never repeat the same test twice unless explicitly investigating flakiness.\n"
    "• If a form has multiple tabs/sections, ensure all fields are visible before filling.\n"
    "• Think step-by-step: Plan → Execute → Verify → Report."
)


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

    if call.name == TEXT_VERIFIER_TOOL_NAME:
        return run_text_verifier_tool(args)
    elif call.name == FORM_FILLER_TOOL_NAME:
        return run_form_filler_tool(args, loader=loader)
    
    return {"error": f"Unknown tool: {call.name}"}


class GeminiAgent:
    def __init__(self, api_key: str, model: str = DEFAULT_MODEL, loader: Optional[PageLoader] = None):
        self.client = genai.Client(api_key=api_key)
        self.model = model
        self.loader = loader
        self.tools = _build_tools()

    def run(self, task: str, max_steps: int = DEFAULT_MAX_STEPS) -> str:
        history: List[types.Content] = [
            types.Content(role="user", parts=[types.Part(text=task)])
        ]

        config = types.GenerateContentConfig(
            systemInstruction=SYSTEM_INSTRUCTION,
            tools=self.tools,
        )

        try:
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
    return settings.gemini.api_key



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
