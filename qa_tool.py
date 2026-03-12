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
import threading

from config import settings
from src.loader import PageLoader
from src.layout_validator import validate_layout
from src.url_verifier import URLVerifier
from src.gemini_agent import GeminiAgent, get_agent, _get_api_key

_PROMPTS_DIR = Path(__file__).parent / "src" / "prompts"


def _load_prompt(name: str) -> str:
    path = _PROMPTS_DIR / name
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    logger.warning(f"Prompt file not found: {path}")
    return ""


# Configure logging
logger = logging.getLogger("qa_tool")


@dataclass
class qa_toolConfig:
    """Configuration for the crawler qa_tool."""
    initial_url: str
    headless: bool = field(default_factory=lambda: settings.browser.headless)
    max_pages: Optional[int] = None
    max_depth: Optional[int] = None
    run_ai: bool = True
    interactive: bool = field(default_factory=lambda: settings.crawler.interactive)
    output_file: Optional[str] = None




@dataclass
class CrawlResult:
    """Holds the results of a full crawl."""
    initial_url: str
    base_domain: str
    internal_reports: List[Dict[str, Any]] = field(default_factory=list)
    external_reports: List[Dict[str, Any]] = field(default_factory=list)
    visited_urls: Set[str] = field(default_factory=set)  
    internal_visited: Set[str] = field(default_factory=set)
    master_qa_audit: str = "Not generated"
    
    # Heap optimization fields
    total_internal_pages_visited: int = 0
    total_external_pages_visited: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Returns the structured report precisely matching the defined schema."""
        return {
            "initial_url": self.initial_url,
            "base_domain": self.base_domain,
            "master_qa_audit": self.master_qa_audit,
            "internal_reports": self.internal_reports,
            "external_reports": self.external_reports,
            "total_internal_pages_visited": self.total_internal_pages_visited or len(self.internal_visited),
            "total_external_pages_visited": self.total_external_pages_visited or len(self.external_reports),
        }



class PageAnalyzer:
    """Analyzes a single page using various tools and the AI agent."""

    def __init__(self, loader: PageLoader):
        self.loader = loader
        self.verifier = URLVerifier()

    async def analyze(self, url: str, deep_analysis: bool = True, run_ai: bool = True, interactive: bool = False) -> Dict[str, Any]:
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
            if deep_analysis and loader_result.get("status") == "success":
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

            # Step 3: AI Agent "Observe and Act" (Initial Verification)
            if run_ai:
                await self._run_agent_analysis(url, base_report)
                
            # Step 4: Interactive Mode (Manual form testing)
            has_forms = False
            if isinstance(base_report.get("forms_html"), dict):
                has_forms = bool(base_report["forms_html"].get("forms"))
            elif isinstance(base_report.get("forms_html"), list):
                has_forms = bool(base_report["forms_html"])

            if interactive and has_forms and run_ai:
                await self._run_interactive_session(url, base_report)

            
            return base_report



        except Exception as exc:
            logger.error(f"Failed to analyze URL {url}: {exc}", exc_info=True)
            return {"url": url, "error": str(exc), "status": "error"}

    async def _run_interactive_session(self, url: str, report: Dict[str, Any]) -> None:
        """Prompts the user for manual form inputs in the terminal."""
        forms_data = report.get("forms_html")
        forms = []
        if isinstance(forms_data, dict):
            forms = forms_data.get("forms", [])
        elif isinstance(forms_data, list):
            forms = forms_data

        if not forms:
            return

        logger.info(f"\n{'#'*80}")
        logger.info(f"✋ INTERACTIVE FORM TESTING for: {url}")
        logger.info(f"   Found {len(forms)} forms. Please provide inputs below.")
        logger.info(f"{'#'*80}")

        
        user_input_map = []

        for i, form in enumerate(forms):
            logger.info(f"\n--- Form {i+1} ---")
            fields = form.get("fields", [])
            form_data = {}
            for field in fields:
                f_name = field.get("name") or field.get("id") or field.get("selector") or "unnamed"
                f_type = field.get("type", "text")
                f_label = field.get("label") or ""
                f_placeholder = field.get("placeholder") or ""
                
                # Skip logic for buttons/submit in data gathering
                if f_type in ("submit", "button", "reset", "hidden"):
                    continue
                
                info = f" ({f_label})" if f_label else ""
                if f_placeholder:
                    info += f" [e.g. {f_placeholder}]"
                
                prompt = f"  👉 {f_name}{info} [{f_type}] > "
                user_val = await asyncio.to_thread(input, prompt)

                if user_val.strip():
                    form_data[f_name] = user_val
            
            if form_data:
                user_input_map.append({
                    "form_index": i,
                    "inputs": form_data
                })

        if user_input_map:
            logger.info("🤖 AI is now testing the forms with your values...")
            await self._run_agent_interactive_testing(url, report, user_input_map)
        else:
            logger.info("  (No manual data provided, skipping interactive test)")

    async def _run_agent_interactive_testing(self, url: str, report: Dict[str, Any], user_input_map: List[Dict[str, Any]]) -> None:
        """Force the AI agent to use specific manual inputs for form testing (Gemini first, fallback OpenAI)."""
        agent = get_agent(loader=self.loader, prefer_gemini=True)
        if not agent:
            return

        interactive_task = _load_prompt("interactive_task.txt").format(
            url=url,
            user_input_json=json.dumps(user_input_map, indent=2),
        )

        try:
            agent_response = await asyncio.to_thread(agent.run, task=interactive_task, max_steps=10)
            report["interactive_session_result"] = agent_response
            logger.info(f"\n🏆 INTERACTIVE TEST RESULT:\n{agent_response}\n")
        except Exception as e:
            logger.error(f"Interactive agent analysis failed for {url}: {e}")
            fallback = get_agent(loader=self.loader, prefer_gemini=False)
            if fallback and type(fallback) != type(agent):
                try:
                    agent_response = await asyncio.to_thread(fallback.run, task=interactive_task, max_steps=10)
                    report["interactive_session_result"] = agent_response
                except Exception as e2:
                    report["interactive_agent_error"] = str(e2)
            else:
                report["interactive_agent_error"] = str(e)

    async def _run_agent_analysis(self, url: str, report: Dict[str, Any]) -> None:
        """Runs the QA agent (Gemini first, fallback OpenAI) to analyze the page report."""
        agent = get_agent(loader=self.loader, prefer_gemini=True)
        if not agent:
            report["agent_error"] = "Missing API key. Set GEMINI_API_KEY and/or OPENAI_API_KEY."
            return

        visible_text = report.get('visible_text') or ''
        task = _load_prompt("qa_task.txt").format(
            url=url,
            url_report=json.dumps(report['url_report'], indent=2),
            layout_report=json.dumps(report['layout_report'], indent=2),
            visible_text=visible_text[:4000] + ('...' if len(visible_text) > 4000 else ''),
            forms_html=json.dumps(report['forms_html'], indent=2),
        )

        logger.info(f"Tasking AI agent for {url}...")
        try:
            agent_response = await asyncio.to_thread(agent.run, task=task)
            report["agent_summary"] = agent_response
            report["_tokens_used"] = getattr(agent, "total_tokens_used", 0)
        except Exception as e:
            logger.error(f"Agent analysis failed for {url}: {e}")
            fallback = get_agent(loader=self.loader, prefer_gemini=False)
            if fallback and type(fallback) != type(agent):
                try:
                    agent_response = await asyncio.to_thread(fallback.run, task=task)
                    report["agent_summary"] = agent_response
                    report["_tokens_used"] = getattr(fallback, "total_tokens_used", 0)
                except Exception as e2:
                    report["agent_error"] = str(e2)
            else:
                report["agent_error"] = str(e)


class BFSCrawler:
    """Manages the Breadth-First Search crawl process."""

    def __init__(self, config: qa_toolConfig, sink: Optional[Any] = None, job_id: Optional[str] = None, cancel_event: Optional[threading.Event] = None):
        self.config = config
        self.sink = sink
        self.job_id = job_id
        self.cancel_event = cancel_event
        
        self.base_domain = self._get_base_domain(config.initial_url)
        self.queue = deque([(config.initial_url, 0)])
        self.results = CrawlResult(initial_url=config.initial_url, base_domain=self.base_domain)
        self.loader = PageLoader(headless=config.headless)
        self.analyzer = PageAnalyzer(self.loader)
        
        # Recycling state
        self.pages_processed = 0
        self.recycle_threshold = getattr(settings.browser, "recycle_pages_threshold", 20)

        # Initialize persistent frontier if sink is provided
        if self.sink and self.job_id:
            self.sink.add_to_frontier(self.job_id, [(config.initial_url, 0, True)])
            self.queue = deque() # Clear in-memory queue, we will use sink

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
            while True:
                # 0. Check cancellation
                if self.cancel_event and self.cancel_event.is_set():
                    logger.info("Crawl cancelled by user.")
                    break

                # 1. Get next URL
                if self.sink and self.job_id:
                    next_item = self.sink.get_next_queued_url(self.job_id)
                    if not next_item:
                        break
                    current_url, current_depth = next_item['url'], next_item['depth']
                    is_internal = bool(next_item['is_internal'])
                else:
                    if not self.queue:
                        break
                    current_url, current_depth = self.queue.popleft()
                    # Dedupe in-memory
                    normalized_url = self._normalize_url(current_url)
                    if normalized_url in self.results.visited_urls:
                        continue
                    self.results.visited_urls.add(normalized_url)
                    is_internal = self._is_internal(current_url)

                # 2. Stop if we hit max pages (only for non-sink mode or global limit)
                # Note: For production with sink, we usually want max_pages to be a property of the job
                processed_count = getattr(self.results, "total_internal_pages_visited", 0) + getattr(self.results, "total_external_pages_visited", 0)
                if self.config.max_pages is not None and processed_count >= self.config.max_pages:
                    logger.info("Reached max pages limit.")
                    break

                # 3. Analyze page
                try:
                    report = await self.analyzer.analyze(
                        current_url, 
                        deep_analysis=is_internal, 
                        run_ai=is_internal and self.config.run_ai,
                        interactive=self.config.interactive
                    )
                except Exception as e:
                    logger.error(f"Critical error analyzing {current_url}: {e}")
                    if self.sink and self.job_id:
                        self.sink.mark_frontier_failed(self.job_id, current_url)
                    continue

                # 4. Handle Results (Stream or Accumulate)
                if self.sink and self.job_id:
                    page_type = 'internal' if is_internal else 'external'
                    self.sink.save_page_report(self.job_id, page_type, report)
                    self.sink.mark_frontier_completed(self.job_id, current_url)

                    tokens = report.pop("_tokens_used", 0)
                    if tokens and hasattr(self.sink, "add_tokens"):
                        self.sink.add_tokens(self.job_id, tokens)

                    if is_internal:
                        self.results.total_internal_pages_visited += 1
                        if self.config.max_depth is None or current_depth < self.config.max_depth:
                            self._discover_urls(current_url, report, current_depth)
                    else:
                        self.results.total_external_pages_visited += 1
                else:
                    if is_internal:
                        self.results.internal_reports.append(report)
                        self.results.internal_visited.add(self._normalize_url(current_url))
                        if self.config.max_depth is None or current_depth < self.config.max_depth:
                            self._discover_urls(current_url, report, current_depth)
                    else:
                        self.results.external_reports.append(report)

                self._log_report(current_url, report)

                # 5. Browser Recycling
                self.pages_processed += 1
                if self.pages_processed >= self.recycle_threshold:
                    logger.info(f"♻️ Recycling browser after {self.pages_processed} pages...")
                    await self.loader.stop()
                    await self.loader.start()
                    self.pages_processed = 0


            if self.config.run_ai:
                await self._generate_master_report()
            else:
                self.results.master_qa_audit = "Skipped: AI analysis disabled."
            
            return self.results

        finally:
            await self.loader.stop()

    def _log_report(self, url: str, report: Dict[str, Any]):
        logger.info(f"\n{'='*80}")
        logger.info(f"📄 REPORT FOR: {url}")
        logger.info(f"{'='*80}")
        if "agent_summary" in report:
            logger.info(report["agent_summary"])
        elif "url_report" in report:
            logger.info(json.dumps(report["url_report"], indent=2))
        elif "error" in report:
            logger.error(f"❌ ERROR: {report['error']}")
        logger.info(f"{'='*80}\n")

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
        
        to_add_to_frontier = []
        for raw_url in discovered_raw:
            if not raw_url or not isinstance(raw_url, str):
                continue
            if raw_url.startswith(("javascript:", "mailto:", "tel:", "#")):
                continue
                
            full_url = urljoin(current_url, raw_url)
            norm_discovered = self._normalize_url(full_url)
            
            if self.sink and self.job_id:
                # Add to persistent frontier batch
                internal = self._is_internal(full_url)
                to_add_to_frontier.append((full_url, current_depth + 1, internal))
            else:
                if norm_discovered not in self.results.visited_urls:
                    self.queue.append((full_url, current_depth + 1))

        if to_add_to_frontier and self.sink and self.job_id:
            self.sink.add_to_frontier(self.job_id, to_add_to_frontier)


    async def _generate_master_report(self):
        """Generates the final AI master report (Gemini first, fallback OpenAI)."""
        reports_to_audit = self.results.internal_reports
        if not reports_to_audit and self.sink and self.job_id:
            # Fetch summary data from DB to avoid loading full reports into memory
            job_data = self.sink.get_job(self.job_id)
            if job_data and job_data.get('result'):
                reports_to_audit = job_data['result'].get('internal_reports', [])

        condensed_results = []
        for r in reports_to_audit:
            url = r.get("url", "unknown")
            url_rep = r.get("url_report") or {}
            status = url_rep.get("status_label", "Error")
            # Safe truncation
            summary = str(r.get("agent_summary", "No summary available."))[:500]
            condensed_results.append({
                "url": url,
                "status": status,
                "summary": summary
            })

        logger.info("🤖 Generating AI Master QA Audit for the whole site...")
        agent = get_agent(loader=None, prefer_gemini=True)
        if not agent:
            logger.warning("Skipping Master Report: No API key (GEMINI_API_KEY or OPENAI_API_KEY).")
            return
        master_task = _load_prompt("master_report_task.txt").format(
            initial_url=self.config.initial_url,
            total_internal=self.results.total_internal_pages_visited or len(self.results.internal_reports),
            total_external=self.results.total_external_pages_visited or len(self.results.external_reports),
            condensed_results=json.dumps(condensed_results, indent=2),
        )
        try:
            self.results.master_qa_audit = await asyncio.to_thread(agent.run, task=master_task)
            tokens = getattr(agent, "total_tokens_used", 0)
            if tokens and self.sink and self.job_id and hasattr(self.sink, "add_tokens"):
                self.sink.add_tokens(self.job_id, tokens)
        except Exception as e:
            logger.error(f"Failed to generate master report: {e}")
            fallback = get_agent(loader=None, prefer_gemini=False)
            if fallback and type(fallback) != type(agent):
                try:
                    self.results.master_qa_audit = await asyncio.to_thread(fallback.run, task=master_task)
                    tokens = getattr(fallback, "total_tokens_used", 0)
                    if tokens and self.sink and self.job_id and hasattr(self.sink, "add_tokens"):
                        self.sink.add_tokens(self.job_id, tokens)
                except Exception as e2:
                    self.results.master_qa_audit = f"Error generating report: {e2}"
            else:
                self.results.master_qa_audit = f"Error generating report: {e}"

        logger.info(f"📊 CRAWL METRICS:")
        logger.info(f" - Internal Pages Visited: {self.results.total_internal_pages_visited or len(self.results.internal_reports)}")
        logger.info(f" - External Links Verified: {self.results.total_external_pages_visited or len(self.results.external_reports)}")
        logger.info(f" - Total Discovered URLs: {self.results.total_internal_pages_visited + self.results.total_external_pages_visited}")

        logger.info(f"{'#'*80}\n")


async def run_qa_tool(config: qa_toolConfig, sink: Optional[Any] = None, job_id: Optional[str] = None, cancel_event: Optional[threading.Event] = None) -> Dict[str, Any]:
    crawler = BFSCrawler(config, sink=sink, job_id=job_id, cancel_event=cancel_event)
    result = await crawler.run()
    return result.to_dict()


def main() -> None:
    parser = argparse.ArgumentParser(description="BFS Crawler qa_tool: Analyze an entire site.")
    parser.add_argument("--url", required=True, help="Starting URL.")
    parser.add_argument("--headless", action=argparse.BooleanOptionalAction, help="Run browser headless.")
    parser.add_argument("--interactive", action="store_true", help="Manually provide form inputs during crawl.")
    parser.add_argument("--output", help="Optional output file path for the JSON result.")

    parser.add_argument("--max-pages", type=int, default=None, help="Max pages to crawl. Default: Unlimited.")
    parser.add_argument("--max-depth", type=int, default=None, help="Max depth to crawl. Default: Unlimited.")

    args = parser.parse_args()
    
    # Setup logging for CLI usage
    logging.basicConfig(
        level=settings.logging_level,
        format="%(asctime)s - [%(levelname)s] - %(name)s - %(message)s",
        datefmt="%H:%M:%S"
    )

    config = qa_toolConfig(
        initial_url=args.url,
        headless=args.headless if args.headless is not None else settings.browser.headless,
        interactive=args.interactive,
        max_pages=args.max_pages if args.max_pages is not None else settings.crawler.max_pages,

        max_depth=args.max_depth if args.max_depth is not None else settings.crawler.max_depth,
        output_file=args.output
    )
    
    try:
        payload = asyncio.run(run_qa_tool(config))
        
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
