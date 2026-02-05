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


async def _run_loader(url: str, headless: bool = True) -> Dict[str, Any]:
    loader = PageLoader(headless=headless)
    await loader.start()
    try:
        return await loader.load(url)
    finally:
        await loader.stop()


def run_pipeline(url: str, headless: bool = True) -> Dict[str, Any]:
    loader_result = asyncio.run(_run_loader(url, headless))

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

    return {
        "url_report": asdict(url_report_obj),
        "layout_report": layout_report,
        "visible_text": loader_result.get("visible_text") or "",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run loader -> url verify -> layout validate.")
    parser.add_argument("--url", required=True, help="Target URL to analyze.")
    parser.add_argument("--headless", action="store_true", help="Run browser headless.")

    args = parser.parse_args()
    payload = run_pipeline(url=args.url, headless=args.headless)
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
