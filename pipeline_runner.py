"""
Pipeline runner with BFS Crawler:
1) Starts with an initial URL.
2) Uses a FIFO queue for BFS traversal.
3) Deduplicates using a hash set.
4) Discovers URLs from various sources (dynamic links, routes, network docs).
5) Filters for internal vs external domains.
6) Runs the full single-page QA suite on each internal page.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import io
import logging
from collections import deque
from contextlib import redirect_stdout
from urllib.parse import urlparse, urljoin
from typing import Any, Dict, List, Set, Optional

from dataclasses import asdict
from AgentBased.loader import PageLoader
from AgentBased.layout_validator import validate_layout
from AgentBased.url_verifier import URLVerifier

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - [%(levelname)s] - %(message)s")
logger = logging.getLogger(__name__)

async def _analyze_single_url(loader: PageLoader, url: str) -> Dict[str, Any]:
    """
    Performs automated checks and agent-led QA on a single page.
    """
    logger.info(f"🔍 Analyzing URL: {url}")
    try:
        # Step 1: Load & Scan
        loader_result = await loader.load(url)
        
        # Step 2: Automated Verification (URL & Layout)
        verifier = URLVerifier()
        url_report_obj = verifier.verify(
            url=url,
            final_url=loader_result.get("final_url"),
            http_status=loader_result.get("http_status"),
            status=loader_result.get("status"),
            error=loader_result.get("error"),
            console_errors=loader_result.get("console_errors") or [],
            navigation_time=loader_result.get("navigation_time_seconds"),
            load_time=loader_result.get("load_time_seconds"),
        )

        # Silence layout validator stdout
        with redirect_stdout(io.StringIO()):
            layout_report = validate_layout(loader_result)

        base_report = {
            "url_report": asdict(url_report_obj),
            "layout_report": layout_report,
            "visible_text": loader_result.get("visible_text") or "",
            "forms_html": loader_result.get("forms_html") or [],
            # These will be used for BFS discovery
            "discovered_urls": loader_result.get("discovered_urls") or [],
            "interactive_routes": loader_result.get("interactive_routes") or [],
            "network_requests": loader_result.get("network_requests") or [],
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
        
        logger.info(f"🤖 Tasking AI agent for {url}...")
        agent_response = agent.run(task=task)
        base_report["agent_summary"] = agent_response

        return base_report

    except Exception as exc:
        logger.error(f"Failed to analyze URL {url}: {exc}")
        return {"url": url, "error": str(exc), "status": "error"}

def _get_base_domain(url: str) -> str:
    parsed = urlparse(url)
    return parsed.netloc

def _is_internal(url: str, base_domain: str) -> bool:
    parsed = urlparse(url)
    # Check if empty netloc (relative path) or matches base_domain
    return parsed.netloc == "" or parsed.netloc == base_domain

async def _run_crawler(initial_url: str, headless: bool = True) -> Dict[str, Any]:
    """
    Crawls the website starting from initial_url using BFS.
    """
    base_domain = _get_base_domain(initial_url)
    queue = deque([initial_url])
    visited: Set[str] = set()
    external_links: Set[str] = set()
    all_reports: List[Dict[str, Any]] = []

    loader = PageLoader(headless=headless)
    await loader.start()

    try:
        while queue:
            current_url = queue.popleft()
            
            # Normalize URL (remove fragments, trailing slashes for deduplication)
            normalized_url = current_url.split('#')[0].rstrip('/')
            if normalized_url in visited:
                continue
            
            visited.add(normalized_url)
            
            # Analyze
            report = await _analyze_single_url(loader, current_url)
            all_reports.append(report)

            # Discover URLs
            discovered_urls = report.get("discovered_urls", [])
            interactive_routes = report.get("interactive_routes", [])
            if isinstance(interactive_routes, dict):
                interactive_routes = interactive_routes.get("urls", [])
            
            network_docs = [
                req["url"] for req in report.get("network_requests", []) 
                if req.get("resource_type") == "document"
            ]

            discovered_raw = discovered_urls + interactive_routes + network_docs

            for raw_url in discovered_raw:
                if not raw_url or not isinstance(raw_url, str):
                    continue
                if raw_url.startswith(("javascript:", "mailto:", "tel:", "#")):
                    continue
                    
                full_url = urljoin(current_url, raw_url)
                
                if _is_internal(full_url, base_domain):
                    norm_discovered = full_url.split('#')[0].rstrip('/')
                    if norm_discovered not in visited:
                        queue.append(full_url)
                else:
                    external_links.add(full_url)

        return {
            "initial_url": initial_url,
            "base_domain": base_domain,
            "internal_reports": all_reports,
            "external_links_found": sorted(list(external_links)),
            "total_internal_pages_visited": len(visited),
        }

    finally:
        await loader.stop()

def run_pipeline(url: str, headless: bool = True) -> Dict[str, Any]:
    return asyncio.run(_run_crawler(url, headless))

def main() -> None:
    parser = argparse.ArgumentParser(description="BFS Crawler Pipeline: Analyze an entire site.")
    parser.add_argument("--url", required=True, help="Starting URL.")
    parser.add_argument("--headless", action="store_true", help="Run browser headless.")

    args = parser.parse_args()
    payload = run_pipeline(url=args.url, headless=args.headless)
    print(json.dumps(payload, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
