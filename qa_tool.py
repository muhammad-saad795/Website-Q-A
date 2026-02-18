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
import sys
import time
import logging

# Fix Windows console encoding for emoji/unicode output
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from pathlib import Path
from collections import deque

from contextlib import redirect_stdout
from urllib.parse import urlparse, urljoin
from typing import Any, Dict, List, Set, Optional
from dataclasses import dataclass, asdict, field

from config import settings
from src.loader import PageLoader
from src.layout_validator import validate_layout
from src.url_verifier import URLVerifier
from src.gemini_agent import GeminiAgent, _get_api_key


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
    visited_urls: Set[str] = field(default_factory=set)  # Tracks ALL unique URLs to avoid re-visits
    internal_visited: Set[str] = field(default_factory=set) # Tracks only internal URLs for accurate count
    master_qa_audit: str = "Not generated"

    def to_dict(self) -> Dict[str, Any]:
        """Returns the structured report precisely matching the defined schema."""
        return {
            "initial_url": self.initial_url,
            "base_domain": self.base_domain,
            "master_qa_audit": self.master_qa_audit,
            "internal_reports": self.internal_reports,
            "external_reports": self.external_reports,
            "total_internal_pages_visited": len(self.internal_visited),
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
        """Force the AI agent to use specific manual inputs for form testing."""
        api_key = _get_api_key()
        if not api_key:
            return

        agent = GeminiAgent(api_key=api_key, loader=self.loader)
        
        # Prepare a specialized task for the agent
        interactive_task = (
            f"🎯 INTERACTIVE FORM TESTING SESSION for {url}\n\n"
            
            "═══════════════════════════════════════════════════════════════\n"
            "👤 USER-PROVIDED TEST DATA\n"
            "═══════════════════════════════════════════════════════════════\n"
            "The user has manually provided specific test values for form validation.\n"
            "This is a targeted test to verify custom scenarios or reproduce specific issues.\n\n"
            f"{json.dumps(user_input_map, indent=2)}\n\n"
            
            "═══════════════════════════════════════════════════════════════\n"
            "🤖 YOUR MISSION\n"
            "═══════════════════════════════════════════════════════════════\n\n"
            
            "STEP 1: FORM IDENTIFICATION\n"
            "├─ Locate the form(s) referenced in the user data (by form_index)\n"
            "├─ Verify all fields mentioned in 'inputs' exist in the form structure\n"
            "└─ If a field is not found by name/ID, intelligently match by label or selector\n\n"
            
            "STEP 2: INTELLIGENT FORM FILLING\n"
            "├─ Use 'intelligent_form_filler' tool with the user's EXACT values\n"
            "├─ Construct the payload: Include ALL normal fields from the form, replacing user-specified ones\n"
            "├─ Field Order: MUST follow HTML top-to-bottom sequence\n"
            "├─ Submit Button: If 'submitSelector' is missing, you MUST find it from the form structure or HTML\n"
            "└─ Set 'submit': true to trigger submission\n\n"
            
            "STEP 3: OUTCOME DIAGNOSIS\n"
            "After submission, perform comprehensive analysis:\n"
            "├─ URL Change: Compare 'url_after_submission' to original URL\n"
            "├─ Success Signals: Search 'visible_text_after_submission' for success messages\n"
            "├─ Error Signals: Look for validation errors, warnings, or failure messages\n"
            "├─ Network Issues: Check 'network_requests_after_submit' for 4xx/5xx errors\n"
            "├─ Console Errors: Review 'console_errors_after_submit' for JavaScript exceptions\n"
            "└─ Root Cause: Determine WHY the submission succeeded or failed\n\n"
            
            "STEP 4: DETAILED REPORTING\n"
            "Generate a professional test report with:\n"
            "├─ Test Scenario: Describe what was tested (e.g., 'Registration with custom email format')\n"
            "├─ Inputs Used: List all field values submitted\n"
            "├─ Expected Outcome: What should have happened?\n"
            "├─ Actual Outcome: What actually happened? (success/failure/partial)\n"
            "├─ Diagnostic Data: URL changes, messages, network/console logs\n"
            "├─ Root Cause Analysis: Why did it succeed/fail?\n"
            "└─ Recommendations: Next steps or fixes needed\n\n"
            
            "⚡ CRITICAL GUIDELINES:\n"
            "• Treat user values as sacred—use them EXACTLY as provided\n"
            "• If you cannot find a submit button, intelligently search for common selectors\n"
            "• Focus on diagnosing the OUTCOME, not just executing the submission\n"
            "• Provide actionable insights the user can act on immediately\n\n"
            
            "Return a clear, professional summary of the test execution and results."
        )
        
        try:
            agent_response = await asyncio.to_thread(agent.run, task=interactive_task, max_steps=10)
            # Store interactive result separately to avoid overwriting initial audit

            report["interactive_session_result"] = agent_response
            logger.info(f"\n🏆 INTERACTIVE TEST RESULT:\n{agent_response}\n")
        except Exception as e:
            logger.error(f"Interactive agent analysis failed for {url}: {e}")
            report["interactive_agent_error"] = str(e)

    async def _run_agent_analysis(self, url: str, report: Dict[str, Any]) -> None:
        """Runs the Gemini agent to analyze the page report."""
        api_key = _get_api_key()

        if not api_key:
            report["agent_error"] = "Missing API key for Gemini Agent."
            return

        agent = GeminiAgent(api_key=api_key, loader=self.loader)
        
        task = (
            f"🎯 MISSION: Comprehensive QA Analysis for {url}\n\n"
            
            "═══════════════════════════════════════════════════════════════\n"
            "📦 SYSTEM DATA PROVIDED\n"
            "═══════════════════════════════════════════════════════════════\n"
            f"1️⃣ URL HEALTH REPORT:\n{json.dumps(report['url_report'], indent=2)}\n\n"
            f"2️⃣ LAYOUT INTEGRITY REPORT:\n{json.dumps(report['layout_report'], indent=2)}\n\n"
            f"3️⃣ PAGE CONTENT (Full Text):\n{report['visible_text'][:4000]}{'...' if len(report['visible_text']) > 4000 else ''}\n\n"
            f"4️⃣ DETECTED FORMS:\n{json.dumps(report['forms_html'], indent=2)}\n\n"
            
            "═══════════════════════════════════════════════════════════════\n"
            "🧠 YOUR ANALYTICAL MISSION\n"
            "═══════════════════════════════════════════════════════════════\n\n"
            
            "PHASE 1: CONTENT VALIDATION\n"
            "├─ Use 'text_verifier' to analyze the visible page text.\n"
            "├─ Verify the content matches the page's inferred purpose (login, registration, product page, etc.).\n"
            "└─ Flag any placeholder text, lorem ipsum, or unfinished content.\n\n"
            
            "PHASE 2: INTELLIGENT FORM TESTING (CRITICAL)\n"
            "If forms are detected, perform EXACTLY 3 DISTINCT test scenarios per form:\n\n"
            
            "  Test 1 - Happy Path (Valid Data):\n"
            "  ├─ Use realistic, valid input for all fields\n"
            "  ├─ Example: Real email format, strong password, typical names\n"
            "  └─ Expected: Successful submission (URL redirect or success message)\n\n"
            
            "  Test 2 - Edge Case (Invalid/Boundary Data):\n"
            "  ├─ Use invalid formats: malformed email, weak password, special characters\n"
            "  ├─ Example: 'invalid-email', 'aaa@', '123', or empty strings\n"
            "  └─ Expected: Client-side validation error or server rejection\n\n"
            
            "  Test 3 - Error Handling (Missing Required Fields):\n"
            "  ├─ Omit at least one required field (set to empty string '')\n"
            "  ├─ Example: Leave 'name' or 'email' blank\n"
            "  └─ Expected: Clear error message identifying the missing field\n\n"
            
            "🔍 POST-SUBMISSION ANALYSIS (MANDATORY FOR EACH TEST):\n"
            "After EVERY form submission, perform deep diagnostics:\n"
            "├─ EXAMINE the 'url_after_submission': Did it redirect? Stay on the same page?\n"
            "├─ ANALYZE 'visible_text_after_submission': Look for success messages, error text, validation warnings\n"
            "├─ INSPECT 'network_requests_after_submit': Check for 4xx/5xx errors, failed API calls\n"
            "├─ REVIEW 'console_errors_after_submit': Identify JavaScript exceptions that prevented submission\n"
            "└─ CORRELATE all signals to determine TRUE outcome (success/fail) and ROOT CAUSE of any issues\n\n"
            
            "⚠️ CRITICAL RULES:\n"
            "• Field Order: MUST match HTML top-to-bottom sequence (validate against forms_html structure)\n"
            "• No Repetition: Do NOT run the same scenario twice. Move to next test immediately.\n"
            "• Stop After 3: Complete exactly 3 scenarios, then STOP form testing.\n"
            "• Multi-Form: If multiple forms exist, test each one following the same 3-scenario protocol.\n\n"
            
            "═══════════════════════════════════════════════════════════════\n"
            "📊 FINAL QA AUDIT REPORT\n"
            "═══════════════════════════════════════════════════════════════\n"
            "Generate a comprehensive, production-ready QA report with these sections:\n\n"
            
            "1. EXECUTIVE SUMMARY\n"
            "   • Overall page health (PASS/WARNING/FAIL)\n"
            "   • Critical issues count and severity breakdown\n\n"
            
            "2. URL HEALTH ASSESSMENT\n"
            "   • HTTP status, redirect behavior, performance metrics\n"
            "   • Console errors from initial load\n\n"
            
            "3. LAYOUT INTEGRITY\n"
            "   • Mobile vs Desktop issues\n"
            "   • Accessibility violations (touch targets, contrast, etc.)\n"
            "   • Severity classification (CRITICAL/WARNING/INFO)\n\n"
            
            "4. CONTENT ACCURACY\n"
            "   • Text verification results\n"
            "   • Alignment with page purpose\n\n"
            
            "5. FORM FUNCTIONALITY (Detailed Test Report)\n"
            "   For EACH form tested, document:\n"
            "   ┌─ Form Identification (index, ID, purpose)\n"
            "   ├─ Field Structure (order, types, required fields)\n"
            "   ├─ Scenario 1 Results: [Inputs] → [Outcome] → [Analysis]\n"
            "   ├─ Scenario 2 Results: [Inputs] → [Outcome] → [Analysis]\n"
            "   ├─ Scenario 3 Results: [Inputs] → [Outcome] → [Analysis]\n"
            "   └─ Root Cause Analysis: Why did failures occur? (e.g., server error, validation bug, missing endpoint)\n\n"
            
            "6. DIAGNOSTIC INSIGHTS\n"
            "   • Network failures: Which endpoints failed and why?\n"
            "   • Console errors: JavaScript exceptions and their impact\n"
            "   • Validation gaps: Missing or insufficient error messages\n\n"
            
            "7. RECOMMENDATIONS\n"
            "   • Prioritized action items for developers\n"
            "   • Quick wins vs. long-term fixes\n"
            "   • Impact assessment (user experience, security, accessibility)\n\n"
            
            "Use professional QA language, quantify all findings, and provide actionable next steps. "
            "Your report should be ready to present to the development team."
        )
        
        logger.info(f"🤖 Tasking AI agent for {url}...")
        try:
            # Removed a CAP of max_steps=10 to allow agent to complete the task
            # WARNING: This may cause the agent to run for a long or infinite time
            # NEEDS proper testing and trust
            agent_response = await asyncio.to_thread(agent.run, task=task)#max_steps=10
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
                # Stop if we hit the max pages limit
                if self.config.max_pages is not None and len(self.results.visited_urls) >= self.config.max_pages:
                    logger.info("Reached max pages limit.")
                    break

                current_url, current_depth = self.queue.popleft()
                normalized_url = self._normalize_url(current_url)
                
                if normalized_url in self.results.visited_urls:
                    continue
                
                self.results.visited_urls.add(normalized_url)
                
                # Determine if internal or external
                is_internal = self._is_internal(current_url)
                if is_internal:
                    self.results.internal_visited.add(normalized_url)
                
                # Analyze page
                report = await self.analyzer.analyze(
                    current_url, 
                    deep_analysis=is_internal, 
                    run_ai=is_internal and self.config.run_ai,
                    interactive=self.config.interactive
                )

                if is_internal:
                    self.results.internal_reports.append(report)
                    
                    if self.config.max_depth is None or current_depth < self.config.max_depth:
                        self._discover_urls(current_url, report, current_depth)
                else:
                    self.results.external_reports.append(report)
                
                self._log_report(current_url, report)


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

        for raw_url in discovered_raw:
            if not raw_url or not isinstance(raw_url, str):
                continue
            if raw_url.startswith(("javascript:", "mailto:", "tel:", "#")):
                continue
                
            full_url = urljoin(current_url, raw_url)
            norm_discovered = self._normalize_url(full_url)
            
            if norm_discovered not in self.results.visited_urls:
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

        logger.info(f"📊 CRAWL METRICS:")
        logger.info(f" - Internal Pages Visited: {len(self.results.internal_reports)}")
        logger.info(f" - External Links Verified: {len(self.results.external_reports)}")
        logger.info(f" - Total Unique URLs Processed: {len(self.results.visited_urls)}")

        logger.info(f"{'#'*80}\n")


async def run_qa_tool(config: qa_toolConfig) -> Dict[str, Any]:
    crawler = BFSCrawler(config)
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
