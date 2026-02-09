"""
Pipeline runner (in-memory only):
1) Load page data with PageLoader
2) Verify URL using AgentBased.url_verifier
3) Validate layout using AgentBased.layout_validator
4) Return a dict with url report, layout report, and visible text
"""

from __future__ import annotations

import argparse
import asyncio
import json
import io
from contextlib import redirect_stdout
from typing import Any, Dict

from dataclasses import asdict
from AgentBased.loader import PageLoader
from AgentBased.layout_validator import validate_layout
from AgentBased.url_verifier import URLVerifier


async def _run_full_pipeline(url: str, headless: bool = True) -> Dict[str, Any]:
    loader = PageLoader(headless=headless)
    await loader.start()
    try:
        # Step 1: Initial Load & Scan
        loader_result = await loader.load(url)
        
        # Step 2: Automated Verification (URL & Layout)
        verifier = URLVerifier()
        url_report_obj = verifier.verify(
            url=loader_result.get("url"),
            final_url=loader_result.get("final_url"),
            http_status=loader_result.get("http_status"),
            status=loader_result.get("status"),
            error=loader_result.get("error"),
            console_errors=loader_result.get("console_errors") or [],
            navigation_time=loader_result.get("navigation_time_seconds"),
            load_time=loader_result.get("load_time_seconds"),
        )

        with redirect_stdout(io.StringIO()):
            layout_report = validate_layout(loader_result)

        base_report = {
            "url_report": asdict(url_report_obj),
            "layout_report": layout_report,
            "visible_text": loader_result.get("visible_text") or "",
            "forms_html": loader_result.get("forms_html") or [],
        }

        # Step 3: AI Agent "Observe and Act"
        from AgentBased.gemini_agent import GeminiAgent, _get_api_key
        
        api_key = _get_api_key()
        if not api_key:
            base_report["agent_error"] = "Missing API key for Gemini Agent."
            return base_report

        agent = GeminiAgent(api_key=api_key, loader=loader)
        
        task = (
            f"You are a Senior QA Automation Engineer. I have performed automated checks for {url}.\n\n"
            "SYSTEM DATA PROVIDED:\n"
            f"1. URL Report: {json.dumps(base_report['url_report'], indent=2)}\n"
            f"2. Layout Report: {json.dumps(base_report['layout_report'], indent=2)}\n"
            f"3. Page Text (excerpt): {base_report['visible_text'][:2000]}\n"
            f"4. Detected Forms: {json.dumps(base_report['forms_html'], indent=2)}\n\n"
            "YOUR MISSION:\n"
            "1. VALIDATE TEXT: Use 'text_verifier' to ensure content matches the page type.\n"
            "2. COMPREHENSIVE FORM TEST: If forms exist, use the 'intelligent_form_filler' tool to test them exhaustively. "
            "STRICT CHRONOLOGICAL ORDER: You MUST process the fields in the EXACT sequential order they appear in the 'forms_html' data. "
            "Your JSON payload keys MUST follow this top-to-bottom, left-to-right flow. NEVER skip or reorder fields. "
            "PAYLOAD REQUIREMENTS: Your tool payload MUST include 'formIndex', all field keys in physical order, 'submitSelector', and 'submit': true.\n"
            "You MUST perform at least THREE test scenarios for each form if possible:\n"
            "   a) Happy Path: All valid and realistic data.\n"
            "   b) Edge Case: Invalid data formats (e.g. bad email, weak password).\n"
            "   c) Error Handling: Omitting a required field.\n"
            "CRITICAL: The JSON payload keys for the tool MUST follow the EXACT sequential order of fields in the HTML.\n"
            "3. FINAL AUDIT: Provide a master QA report covering URL health, Layout integrity, Content accuracy, and "
            "a detailed breakdown of all form test scenarios performed (Inputs used -> Outcomes recorded).\n"
            "Your goal is to ensure the form is robust and behaves correctly under various conditions."
        )
        
        print("\n[PIPELINE] Tasking AI agent with full QA audit...")
        agent_response = agent.run(task=task)
        base_report["agent_summary"] = agent_response

        return base_report

    finally:
        await loader.stop()


def run_pipeline(url: str, headless: bool = True) -> Dict[str, Any]:
    return asyncio.run(_run_full_pipeline(url, headless))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run loader -> url verify -> layout validate -> AI agent.")
    parser.add_argument("--url", required=True, help="Target URL to analyze.")
    parser.add_argument("--headless", action="store_true", help="Run browser headless.")

    args = parser.parse_args()
    payload = run_pipeline(url=args.url, headless=args.headless)
    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
