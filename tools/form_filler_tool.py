"""
Gemini tool: intelligent_form_filler

This tool executes form submission on a target URL.
It can reuse an existing PageLoader's browser context for performance,
or fall back to launching its own browser instance.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional, List
import asyncio
import logging
from playwright.async_api import async_playwright, Page, Error as PlaywrightError

from dotenv import load_dotenv
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", "src", ".env"), override=True)

TOOL_NAME = "intelligent_form_filler"
logger = logging.getLogger(__name__)

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
                "description": "Run browser in headless mode. Default: true",
            },
        },
        "required": ["url", "payload"],
    },
}


# ──────────────────────────────────────────────
# SMART WAIT HELPER
# ──────────────────────────────────────────────

async def _smart_wait_after_submit(page: Page, timeout_ms: int = 10000) -> None:
    """Wait for navigation or network idle after form submit, with fallback."""
    try:
        await page.wait_for_load_state("networkidle", timeout=timeout_ms)
    except PlaywrightError:
        await asyncio.sleep(3)


# ──────────────────────────────────────────────
# SHARED-LOADER PATH (reuses crawler browser)
# ──────────────────────────────────────────────

async def _submit_via_loader(
    loader: Any,
    url: str,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    """Reuse an existing PageLoader's browser context instead of cold-launching a new browser."""
    if not loader.context:
        return {"error": "PageLoader has no active browser context."}

    page = await loader.context.new_page()
    network_logs: List[Dict[str, Any]] = []
    console_logs: List[Dict[str, Any]] = []

    def on_response(res):
        network_logs.append({
            "url": res.url, "status": res.status,
            "method": res.request.method, "resource_type": res.request.resource_type,
        })

    def on_console(msg):
        if msg.type in ("error", "warning"):
            console_logs.append({"type": msg.type, "text": msg.text})

    page.on("response", on_response)
    page.on("console", on_console)

    try:
        await page.goto(url, wait_until="networkidle", timeout=30000)

        if SCAN_FORMS_SCRIPT.exists():
            await page.evaluate(SCAN_FORMS_SCRIPT.read_text())
        else:
            return {"error": f"Scan script missing at {SCAN_FORMS_SCRIPT}"}

        if not FILL_FORMS_SCRIPT.exists():
            return {"error": f"Fill script missing at {FILL_FORMS_SCRIPT}"}

        network_logs.clear()
        console_logs.clear()

        fill_result = await page.evaluate(FILL_FORMS_SCRIPT.read_text(), payload)
        await _smart_wait_after_submit(page)

        visible_text = ""
        if EXTRACT_TEXT_SCRIPT.exists():
            visible_text = await page.evaluate(EXTRACT_TEXT_SCRIPT.read_text())

        return {
            "status": "success",
            "fill_details": fill_result,
            "url_after_submission": page.url,
            "visible_text_after_submission": visible_text,
            "network_requests_after_submit": network_logs,
            "console_errors_after_submit": console_logs,
        }
    except Exception as exc:
        logger.error(f"Form submission via loader failed: {exc}")
        return {"error": str(exc)}
    finally:
        try:
            page.remove_listener("response", on_response)
            page.remove_listener("console", on_console)
        except Exception:
            pass
        await page.close()


# ──────────────────────────────────────────────
# STANDALONE PATH (own browser lifecycle)
# ──────────────────────────────────────────────

async def _submit_form_workflow(
    url: str,
    payload: Dict[str, Any],
    headless: bool = True,
) -> Dict[str, Any]:
    """Standalone workflow: Start browser, navigate, scan, and fill."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(viewport={"width": 1280, "height": 720})
        page = await context.new_page()

        network_logs: List[Dict[str, Any]] = []
        console_logs: List[Dict[str, Any]] = []

        page.on("response", lambda res: network_logs.append({
            "url": res.url, "status": res.status,
            "method": res.request.method, "resource_type": res.request.resource_type,
        }))
        page.on("console", lambda msg: console_logs.append({
            "type": msg.type, "text": msg.text,
        }) if msg.type in ("error", "warning") else None)

        try:
            logger.info(f"Navigating to {url}...")
            await page.goto(url, wait_until="networkidle", timeout=30000)

            if SCAN_FORMS_SCRIPT.exists():
                await page.evaluate(SCAN_FORMS_SCRIPT.read_text())
            else:
                return {"error": f"Scan script missing at {SCAN_FORMS_SCRIPT}"}

            if not FILL_FORMS_SCRIPT.exists():
                return {"error": f"Fill script missing at {FILL_FORMS_SCRIPT}"}

            network_logs.clear()
            console_logs.clear()

            fill_result = await page.evaluate(FILL_FORMS_SCRIPT.read_text(), payload)
            await _smart_wait_after_submit(page)

            visible_text = ""
            if EXTRACT_TEXT_SCRIPT.exists():
                visible_text = await page.evaluate(EXTRACT_TEXT_SCRIPT.read_text())

            return {
                "status": "success",
                "fill_details": fill_result,
                "url_after_submission": page.url,
                "visible_text_after_submission": visible_text,
                "network_requests_after_submit": network_logs,
                "console_errors_after_submit": console_logs,
            }
        except Exception as exc:
            logger.error(f"Form submission workflow failed: {exc}")
            return {"error": str(exc)}
        finally:
            if not headless:
                await asyncio.sleep(1)
            await browser.close()


def run_form_filler_tool(args: Dict[str, Any], loader: Optional[Any] = None) -> Dict[str, Any]:
    """
    Runtime wrapper for the intelligent_form_filler tool.
    Reuses the shared PageLoader's browser when available; falls back to standalone.
    """
    url = args.get("url")
    payload = args.get("payload")
    headless = args.get("headless", True)

    if not url or not payload:
        return {"error": "Missing required arguments: 'url' and 'payload'."}

    try:
        # Prefer shared loader path when a live browser context is available
        use_loader = loader is not None and getattr(loader, "context", None) is not None

        if use_loader:
            coro = _submit_via_loader(loader, url, payload)
        else:
            coro = _submit_form_workflow(url, payload, headless)

        try:
            loop = asyncio.get_running_loop()
            import nest_asyncio
            nest_asyncio.apply()
            return loop.run_until_complete(coro)
        except RuntimeError:
            return asyncio.run(coro)
    except Exception as exc:
        return {"error": f"Tool execution crashed: {exc}"}


__all__ = [
    "TOOL_NAME",
    "GEMINI_TOOL_SPEC",
    "run_form_filler_tool",
]
