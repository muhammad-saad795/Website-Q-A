"""
Gemini tool: intelligent_form_filler

This tool executes form submission on a target URL. 
It manages its own browser instance, navigates to the page, 
scans for forms, and then fills/submits using the provided payload.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional, List
import asyncio
import logging
from playwright.async_api import async_playwright

# Load environment variables from the src/.env file
from dotenv import load_dotenv
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", "src", ".env"), override=True)

TOOL_NAME = "intelligent_form_filler"
logger = logging.getLogger(__name__)

# Paths to helper scripts
BASE_DIR = Path(__file__).parent.parent
SCRIPTS_DIR = BASE_DIR / "src" / "scripts"
SCAN_FORMS_SCRIPT = SCRIPTS_DIR / "scan_forms.js"
FILL_FORMS_SCRIPT = SCRIPTS_DIR / "fill_forms.js"
EXTRACT_TEXT_SCRIPT = SCRIPTS_DIR / "extract_visible_text.js"

# ──────────────────────────────────────────────
# TOOL SPECIFICATION
# ──────────────────────────────────────────────

GEMINI_TOOL_SPEC: Dict[str, Any] = {
    "name": TOOL_NAME,
    "description": (
        "Automatically navigate to a URL and submit a form using a provided JSON payload. "
        "The tool will handle page navigation, form detection, and submission execution. "
        "The payload MUST contain: 'formIndex' (int), 'submitSelector' (valid CSS selector), and all field selectors in top-to-bottom order."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The URL of the page where the form is located.",
            },
            "payload": {
                "type": "object",
                "description": (
                    "The JSON object containing form data. "
                    "Example: {'formIndex': 0, '#email': 'user@example.com', 'submitSelector': 'button[type=submit]', 'submit': true}"
                ),
            },
            "headless": {
                "type": "boolean",
                "description": "Run browser in headless mode. Default: false",
            },
        },
        "required": ["url", "payload"],
    },
}

# ──────────────────────────────────────────────
# TOOL RUNTIME
# ──────────────────────────────────────────────

async def _submit_form_workflow(
    url: str,
    payload: Dict[str, Any],
    headless: bool = False,
) -> Dict[str, Any]:
    """
    Standalone workflow: Start browser, navigate, scan, and fill.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(viewport={"width": 1280, "height": 720})
        page = await context.new_page()
        
        network_logs = []
        console_logs = []
        
        page.on("response", lambda res: network_logs.append({
            "url": res.url,
            "status": res.status,
            "method": res.request.method,
            "resource_type": res.request.resource_type
        }))
        page.on("console", lambda msg: console_logs.append({
            "type": msg.type,
            "text": msg.text
        }) if msg.type in ("error", "warning") else None)

        try:
            logger.info(f"🚀 Navigating to {url}...")
            await page.goto(url, wait_until="networkidle", timeout=30000)
            
            # Step 1: Scan for forms to initialize window.__FORMS_STATE__
            if SCAN_FORMS_SCRIPT.exists():
                logger.info("Scanning forms...")
                scan_script = SCAN_FORMS_SCRIPT.read_text()
                await page.evaluate(scan_script)
            else:
                return {"error": f"Scan script missing at {SCAN_FORMS_SCRIPT}"}
            
            # Step 2: Fill and Submit
            if FILL_FORMS_SCRIPT.exists():
                # Clear logs before submission to focus on events triggered by the submit click
                network_logs.clear()
                console_logs.clear()

                logger.info(f"✍️ Submitting form with payload: {json.dumps(payload, indent=2)}")
                fill_script = FILL_FORMS_SCRIPT.read_text()
                # fill_forms.js is an async function: async (payload) => { ... }
                fill_result = await page.evaluate(fill_script, payload)
                
                # Wait for potential navigation or success message
                logger.info("Waiting 15 seconds for submission to process...")
                await asyncio.sleep(15) 
                
                # Step 3: Extract visible text after submission
                visible_text = ""
                if EXTRACT_TEXT_SCRIPT.exists():
                    logger.info("Extracting page text after submission...")
                    text_script = EXTRACT_TEXT_SCRIPT.read_text()
                    visible_text = await page.evaluate(text_script)
                
                final_url = page.url
                return {
                    "status": "success",
                    "fill_details": fill_result,
                    "url_after_submission": final_url,
                    "visible_text_after_submission": visible_text,
                    "network_requests_after_submit": network_logs,
                    "console_errors_after_submit": console_logs
                }
            else:
                return {"error": f"Fill script missing at {FILL_FORMS_SCRIPT}"}


        except Exception as exc:
            logger.error(f"Form submission workflow failed: {exc}")
            return {"error": str(exc)}
        finally:
            # Short wait for visual confirmation if not headless
            if not headless:
                await asyncio.sleep(1)
            await browser.close()

def run_form_filler_tool(args: Dict[str, Any], loader: Optional[Any] = None) -> Dict[str, Any]:
    """
    Runtime wrapper for the intelligent_form_filler tool.
    This version ignores any shared loader and uses its own lifecycle.
    """
    url = args.get("url")
    payload = args.get("payload")
    headless = args.get("headless", False)

    if not url or not payload:
        return {"error": "Missing required arguments: 'url' and 'payload'."}

    # Since we are running in an async-capable environment (usually called by agent.run),
    # we use a helper to run the async workflow.
    try:
        # Check if we can use an existing loop or need to create one
        try:
            loop = asyncio.get_running_loop()
            import nest_asyncio
            nest_asyncio.apply()
            return loop.run_until_complete(_submit_form_workflow(url, payload, headless))
        except RuntimeError:
            return asyncio.run(_submit_form_workflow(url, payload, headless))
    except Exception as exc:
        return {"error": f"Tool execution crashed: {exc}"}

__all__ = [
    "TOOL_NAME",
    "GEMINI_TOOL_SPEC",
    "run_form_filler_tool",
]
