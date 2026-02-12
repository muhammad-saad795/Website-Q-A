"""
qa_tool with BFS Crawler:
1) Starts with an initial URL.
2) Uses a FIFO queue for BFS traversal.
3) Deduplicates using a hash set.
4) Discovers URLs from various sources (dynamic links, routes, network docs).
5) Filters for internal vs external domains.
6) Runs the full single-page QA suite on each internal page.
"""
#Usage : python qa_tool.py --url <url> --headless --max-pages <max_pages> --max-depth <max_depth> --output <output_file>
from __future__ import annotations

import argparse
import asyncio
import json
import io
import time
import logging

from pathlib import Path
from collections import deque

from contextlib import redirect_stdout
from urllib.parse import urlparse, urljoin
from typing import Any, Dict, List, Set, Optional
from dataclasses import dataclass, asdict, field

from config import settings
from AgentBased.loader import PageLoader
from AgentBased.layout_validator import validate_layout
from AgentBased.url_verifier import URLVerifier
from AgentBased.gemini_agent import GeminiAgent, _get_api_key


# Configure logging
logging.basicConfig(
    level=settings.logging_level,
    format="%(asctime)s - [%(levelname)s] - %(name)s - %(message)s",
    datefmt="%H:%M:%S"
)

logger = logging.getLogger("qa_tool")


@dataclass
class qa_toolConfig:
    """Configuration for the crawler qa_tool."""
    initial_url: str
    headless: bool = field(default_factory=lambda: settings.browser.headless)
    max_pages: Optional[int] = field(default_factory=lambda: settings.crawler.max_pages)
    max_depth: Optional[int] = field(default_factory=lambda: settings.crawler.max_depth)
    output_file: Optional[str] = None



@dataclass
class CrawlResult:
    """Holds the results of a full crawl."""
    initial_url: str
    base_domain: str
    internal_reports: List[Dict[str, Any]] = field(default_factory=list)
    external_reports: List[Dict[str, Any]] = field(default_factory=list)
    visited_pages: Set[str] = field(default_factory=set)
    master_qa_audit: str = "Not generated"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "initial_url": self.initial_url,
            "base_domain": self.base_domain,
            "master_qa_audit": self.master_qa_audit,
            "internal_reports": self.internal_reports,
            "external_reports": self.external_reports,
            "total_internal_pages_visited": len(self.visited_pages),
        }



class PageAnalyzer:
    """Analyzes a single page using various tools and the AI agent."""

    def __init__(self, loader: PageLoader):
        self.loader = loader
        self.verifier = URLVerifier()

    async def analyze(self, url: str, deep_analysis: bool = True, run_ai: bool = True) -> Dict[str, Any]:
        """Performs automated checks and conditionally runs agent-led QA."""
        logger.info(f"🔍 Analyzing URL ({'Internal' if deep_analysis else 'External'}): {url}")
        
        try:
            # Step 1: Load & Scan
            loader_result = await self.loader.load(url, deep_analysis=deep_analysis)
            
            # Step 2: Automated Verification (URL & Layout)
            url_report_obj = self.verifier.verify(
                url=url,
                final_url=loader_result.get("final_url"),
                http_status=loader_result.get("http_status"),
                status=loader_result.get("status"),
                error=loader_result.get("error"),
                console_errors=loader_result.get("console_errors") or [],
                navigation_time=loader_result.get("navigation_time_seconds"),
                load_time=loader_result.get("load_time_seconds"),
            )

            # Silence layout validator stdout for external urls if requested
            layout_report = None
            if deep_analysis:
                with redirect_stdout(io.StringIO()):
                    layout_report = validate_layout(loader_result)

            base_report = {
                "url": url,
                "url_report": asdict(url_report_obj),
                "layout_report": layout_report,
                "visible_text": loader_result.get("visible_text"),
                "forms_html": loader_result.get("forms_html"),
                "discovered_urls": loader_result.get("discovered_urls") or [],
                "interactive_routes": loader_result.get("interactive_routes") or [],
                "network_requests": loader_result.get("network_requests") or [],
            }

            # Step 3: AI Agent "Observe and Act" (Skipped for external links)
            if run_ai:
                await self._run_agent_analysis(url, base_report)
            
            return base_report


        except Exception as exc:
            logger.error(f"Failed to analyze URL {url}: {exc}", exc_info=True)
            return {"url": url, "error": str(exc), "status": "error"}

    async def _run_agent_analysis(self, url: str, report: Dict[str, Any]) -> None:
        """Runs the Gemini agent to analyze the page report."""
        api_key = _get_api_key()
        if not api_key:
            report["agent_error"] = "Missing API key for Gemini Agent."
            return

        agent = GeminiAgent(api_key=api_key, loader=self.loader)
        
        task = (
            f"You are a Senior QA Automation Engineer. I have performed automated checks for {url}.\n\n"
            "SYSTEM DATA PROVIDED:\n"
            f"1. URL Report: {json.dumps(report['url_report'], indent=2)}\n"
            f"2. Layout Report: {json.dumps(report['layout_report'], indent=2)}\n"
            f"3. Page Text (excerpt): {report['visible_text']}\n"
            f"4. Detected Forms: {json.dumps(report['forms_html'], indent=2)}\n\n"
            "YOUR MISSION:\n"
            "1. VALIDATE TEXT: Use 'text_verifier' to make sure the content matches the page type.\n"
            "2. FORM TESTING (Strict Limit): If forms exist, use 'intelligent_form_filler' to test them.\n"
            "   - Perform EXACTLY THREE distinct scenarios per form: 1) Happy Path (Valid), 2) Edge Case (Invalid/Boundary), 3) Error Handling (Missing fields).\n"
            "   - DO NOT REPEAT any scenario. If a scenario is completed, move to the next one.\n"
            "   - STOP testing after 3 attempts, regardless of the outcome.\n"
            "   - CRITICAL: Your JSON payload keys MUST follow the EXACT sequential order of fields in the HTML.\n"
            "3. FINAL AUDIT: Provide a master QA report covering URL health, Layout integrity, Content accuracy, and "
            "a detailed breakdown of the 3 form test scenarios performed (Inputs used -> Outcomes recorded).\n"
        )
        
        logger.info(f"🤖 Tasking AI agent for {url}...")
        try:
            agent_response = await asyncio.to_thread(agent.run, task=task, max_steps=10)
            report["agent_summary"] = agent_response
        except Exception as e:
            logger.error(f"Agent analysis failed for {url}: {e}")
            report["agent_error"] = str(e)


class BFSCrawler:
    """Manages the Breadth-First Search crawl process."""

    def __init__(self, config: qa_toolConfig):
        self.config = config
        self.base_domain = self._get_base_domain(config.initial_url)
        self.queue = deque([(config.initial_url, 0)])
        self.results = CrawlResult(initial_url=config.initial_url, base_domain=self.base_domain)
        self.loader = PageLoader(headless=config.headless)
        self.analyzer = PageAnalyzer(self.loader)

    def _get_base_domain(self, url: str) -> str:
        parsed = urlparse(url)
        return parsed.netloc

    def _is_internal(self, url: str) -> bool:
        parsed = urlparse(url)
        return parsed.netloc == "" or parsed.netloc == self.base_domain

    def _normalize_url(self, url: str) -> str:
        return url.split('#')[0].rstrip('/')

    async def run(self) -> CrawlResult:
        """Executes the crawl."""
        await self.loader.start()
        
        try:
            while self.queue:
                if self.config.max_pages is not None and len(self.results.visited_pages) >= self.config.max_pages:
                    logger.info("Reached max pages limit.")
                    break

                current_url, current_depth = self.queue.popleft()
                normalized_url = self._normalize_url(current_url)
                
                if normalized_url in self.results.visited_pages:
                    continue
                
                self.results.visited_pages.add(normalized_url)
                
                # Determine if internal or external
                is_internal = self._is_internal(current_url)
                
                # Analyze page
                # If external: deep_analysis=False, run_ai=False
                report = await self.analyzer.analyze(
                    current_url, 
                    deep_analysis=is_internal, 
                    run_ai=is_internal
                )
                
                if is_internal:
                    self.results.internal_reports.append(report)
                    if self.config.max_depth is None or current_depth < self.config.max_depth:
                        self._discover_urls(current_url, report, current_depth)
                else:
                    self.results.external_reports.append(report)
                
                self._log_report(current_url, report)


            await self._generate_master_report()
            
            return self.results

        finally:
            await self.loader.stop()

    def _log_report(self, url: str, report: Dict[str, Any]):
        print(f"\n{'='*80}")
        print(f"📄 REPORT FOR: {url}")
        print(f"{'='*80}")
        if "agent_summary" in report:
            print(report["agent_summary"])
        elif "error" in report:
            print(f"❌ ERROR: {report['error']}")
        print(f"{'='*80}\n")

    def _discover_urls(self, current_url: str, report: Dict[str, Any], current_depth: int):
        discovered_urls = report.get("discovered_urls", [])
        interactive_routes = report.get("interactive_routes", [])
        
        # Handle case where interactive_routes might be a dict or list
        if isinstance(interactive_routes, dict):
            interactive_routes = interactive_routes.get("urls", [])
        
        network_docs = [
            req["url"] for req in report.get("network_requests", []) 
            if req.get("resource_type") == "document"
        ]

        # Combine all sources
        discovered_raw = discovered_urls + interactive_routes + network_docs

        for raw_url in discovered_raw:
            if not raw_url or not isinstance(raw_url, str):
                continue
            if raw_url.startswith(("javascript:", "mailto:", "tel:", "#")):
                continue
                
            full_url = urljoin(current_url, raw_url)
            norm_discovered = self._normalize_url(full_url)
            
            if norm_discovered not in self.results.visited_pages:
                # Add to queue regardless of internal/external,
                # the run loop will handle the analysis logic.
                self.queue.append((full_url, current_depth + 1))


    async def _generate_master_report(self):
        """Generates the final AI master report."""
        api_key = _get_api_key()
        if not api_key:
            logger.warning("Skipping Master Report: Missing API key.")
            return

        condensed_results = []
        for r in self.results.internal_reports:
            url = r.get("url", "unknown")
            status = r.get("url_report", {}).get("status_label", "Error")
            # Safe truncation
            summary = str(r.get("agent_summary", "No summary available."))[:500]
            condensed_results.append({
                "url": url,
                "status": status,
                "summary": summary
            })

        logger.info("🤖 Generating AI Master QA Audit for the whole site...")
        
        agent = GeminiAgent(api_key=api_key)
        master_task = (
            f"You are a Lead QA Engineer. I have crawled the website starting at {self.config.initial_url}.\n"
            f"Total Internal Pages Visited: {len(self.results.internal_reports)}\n"
            f"Total External Links Verified: {len(self.results.external_reports)}\n\n"
            "Here is a summary of the findings for internal pages:\n"

            f"{json.dumps(condensed_results, indent=2)}\n\n"
            "YOUR MISSION:\n"
            "Provide a high-level 'Master QA Audit' for the entire website. "
            "Highlight recurring issues, overall site health, and critical areas that need attention. "
            "DO NOT call any tools. Provide your response as a professional, thorough text-only report."
        )
        
        try:
            self.results.master_qa_audit = await asyncio.to_thread(agent.run, task=master_task)
        except Exception as e:

            logger.error(f"Failed to generate master report: {e}")
            self.results.master_qa_audit = f"Error generating report: {e}"

        print(f"📊 CRAWL METRICS:")
        print(f" - Internal Pages Visited: {len(self.results.internal_reports)}")
        print(f" - External Links Verified: {len(self.results.external_reports)}")
        print(f" - Total Unique URLs Processed: {len(self.results.visited_pages)}")

        print(f"{'#'*80}\n")


async def run_qa_tool(config: qa_toolConfig) -> Dict[str, Any]:
    crawler = BFSCrawler(config)
    result = await crawler.run()
    return result.to_dict()


def main() -> None:
    parser = argparse.ArgumentParser(description="BFS Crawler qa_tool: Analyze an entire site.")
    parser.add_argument("--url", required=True, help="Starting URL.")
    parser.add_argument("--headless", action="store_true", help="Run browser headless.")
    parser.add_argument("--output", help="Optional output file path for the JSON result.")
    parser.add_argument("--max-pages", type=int, default=None, help="Max pages to crawl. Default: Unlimited.")
    parser.add_argument("--max-depth", type=int, default=None, help="Max depth to crawl. Default: Unlimited.")

    args = parser.parse_args()
    
    config = qa_toolConfig(
        initial_url=args.url,
        headless=args.headless,
        max_pages=args.max_pages,
        max_depth=args.max_depth,
        output_file=args.output
    )
    
    try:
        payload = asyncio.run(run_qa_tool(config))
        
        # Always print JSON to stdout for data piping
        print(json.dumps(payload, indent=2, ensure_ascii=False))

        # Optionally save to file
        if config.output_file:
            output_path = Path(config.output_file)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            logger.info(f"Results saved to {output_path}")
        else:
            # Save to default output dir if no output file specified
            output_dir = Path(settings.crawler.output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
            domain = urlparse(config.initial_url).netloc.replace(".", "_")
            timestamp = time.strftime("%Y%m%d-%H%M%S")
            output_path = output_dir / f"crawl_{domain}_{timestamp}.json"
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            logger.info(f"Results saved to {output_path}")

            
    except KeyboardInterrupt:
        logger.warning("qa_tool interrupted by user.")
    except Exception as e:
        logger.critical(f"qa_tool failed: {e}", exc_info=True)

if __name__ == "__main__":
    main()
