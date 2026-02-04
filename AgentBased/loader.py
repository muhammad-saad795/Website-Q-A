import asyncio
import logging
import time
from pathlib import Path
from typing import Optional, Dict, Any, List
from playwright.async_api import async_playwright, Browser, BrowserContext, Page, Error as PlaywrightError


# ──────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────
MAX_LOAD_SECONDS = 60
NAV_TIMEOUT_MS = 30_000
SETTLE_TIME_MS = 1_000
RETRIES = 3  # retry on connection failures

logging.basicConfig(level=logging.INFO, format="%(asctime)s - [%(levelname)s] - %(message)s")
logger = logging.getLogger(__name__)


class PageLoader:
    def __init__(self, headless: bool = False):
        self.headless = headless
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self._stop_event: Optional[asyncio.Event] = None  # Event to signal when stop() is called
        self._keep_alive_page: Optional[Page] = None  # Page to keep browser window open

        # Scripts directory
        self.scripts_dir = Path("scripts")
        self.scroll_script_path = self.scripts_dir / "scroll_page.js"
        self.text_script_path = self.scripts_dir / "extract_visible_text.js"
        self.layout_snapshot_script_path = self.scripts_dir / "layout_snapshot.js"
        self.dynamic_links_script_path = self.scripts_dir / "dynamic_links_capture.js"
        self.interactive_route_discovery_path = self.scripts_dir / "interactive_route_discovery.js"
        self.form_html_extractor_script_path = self.scripts_dir / "scan_forms.js"
        self.form_detector_script_path = self.scripts_dir / "form_detector.js"
        self.form_automation_script_path = self.scripts_dir / "automate_form.js"

    async def start(self):
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=self.headless)
        self.context = await self.browser.new_context(ignore_https_errors=True)
        # Create stop event within async context to ensure it's bound to the current event loop
        self._stop_event = asyncio.Event() 
        
    async def stop(self):
        # Close keep-alive page first
        if self._keep_alive_page:
            await self._keep_alive_page.close()
            self._keep_alive_page = None
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
        # Signal that stop() has been called
        if self._stop_event:
            self._stop_event.set()

    async def _scroll_page(self, page: Page):
        if not self.scroll_script_path.exists():
            logger.warning("Scroll script not found, skipping scroll.")
            return
        script = self.scroll_script_path.read_text(encoding='utf-8')
        try:
            await page.evaluate(script)
        except PlaywrightError as e:
            logger.warning(f"Scroll script execution failed: {e}")

    async def _extract_visible_text(self, page: Page) -> str:
        if not self.text_script_path.exists():
            logger.warning("Text extraction script not found.")
            return ""
        script = self.text_script_path.read_text(encoding='utf-8')
        try:
            return await page.evaluate(script)
        except PlaywrightError as e:
            logger.warning(f"Text extraction failed: {e}")
            return ""

    async def _capture_layout_snapshot(self, page: Page) -> Dict[str, Any]:
        if not self.layout_snapshot_script_path.exists():
            logger.warning("Layout snapshot script not found.")
            return {}
        script = self.layout_snapshot_script_path.read_text(encoding='utf-8')
        try:
            return await page.evaluate(script)
        except PlaywrightError as e:
            logger.warning(f"Layout snapshot failed: {e}")
            return {}
    
    async def _capture_dynamic_links(self, page: Page) -> List[str]:
        if self.dynamic_links_script_path.exists():
            return await page.evaluate(self.dynamic_links_script_path.read_text(encoding='utf-8'))
        return []

    async def _discover_interactive_routes(self, page: Page):
        if self.interactive_route_discovery_path.exists():
            return await page.evaluate(self.interactive_route_discovery_path.read_text(encoding='utf-8'))
            page.wait_for_timeout(SETTLE_TIME_MS)
        return []
    async def _scan_forms(self, page: Page):
        if self.form_html_extractor_script_path.exists():
            return await page.evaluate(self.form_html_extractor_script_path.read_text(encoding='utf-8'))
        return []
    async def _detect_forms(self, page: Page) -> List[Dict[str, Any]]:
        if not self.form_detector_script_path.exists():
            logger.warning("Form detector script not found.")
            return []
        script = self.form_detector_script_path.read_text(encoding='utf-8')
        try:
            return await page.evaluate(script)
        except PlaywrightError as e:
            logger.warning(f"Form detection failed: {e}")
            return []

    async def _load_page(self, page: Page, url: str, result: Dict[str, Any]):
        # ── Setup listeners before navigation ──
        network_requests: List[Dict[str, Any]] = []
        console_errors: List[Dict[str, Any]] = []

        # Define named callbacks for removal
        def on_response(r):
            network_requests.append({
                "url": r.url,
                "status": r.status,
                "method": r.request.method,
                "resource_type": r.request.resource_type
            })

        def on_console(m):
            if m.type in ("error", "warning"):
                console_errors.append({
                    "type": m.type,
                    "text": m.text,
                    "location": m.location
                })

        # Attach listeners
        page.on("response", on_response)
        page.on("console", on_console)

        # ── Navigate ──
        start_time = time.perf_counter()
        response = await page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
        navigation_time = time.perf_counter() - start_time
        
        if not response:
            raise RuntimeError("No response received")

        result["final_url"] = page.url
        result["http_status"] = response.status
        result["status"] = "success" if response.ok else "failed"
        result["navigation_time_seconds"] = navigation_time

        try:
            await page.wait_for_load_state("networkidle", timeout=NAV_TIMEOUT_MS)
            result["load_time_seconds"] = time.perf_counter() - start_time
        except PlaywrightError:
            logger.warning("networkidle not reached, continuing")
            result["load_time_seconds"] = time.perf_counter() - start_time

        # ── Lazy-load scrolling ──
        await self._scroll_page(page)
        await page.wait_for_timeout(SETTLE_TIME_MS)

        # ── Capture HTML, visible text, and layout snapshot ──
        result["html"] = await page.content()
        result["visible_text"] = await self._extract_visible_text(page)
        #Discover urls
        result["discovered_urls"] = await self._capture_dynamic_links(page)

        # Desktop
        #----Page already in desktop mode----
        result["layout_snapshot_desktop"] = await self._capture_layout_snapshot(page)
        
        # Mobile
        await page.set_viewport_size({"width": 375, "height": 812})
        await page.wait_for_timeout(SETTLE_TIME_MS)
        result["layout_snapshot_mobile"] = await self._capture_layout_snapshot(page)
        #-----Set back to desktop mode (Maximized)-----
        await page.set_viewport_size({"width": 1280, "height": 720})
        await page.wait_for_timeout(SETTLE_TIME_MS)

        # ── Add network & console logs ──
        result["network_requests"] = network_requests
        result["console_errors"] = console_errors

        # Explicitly remove listeners to stop tracking
        page.remove_listener("response", on_response)
        page.remove_listener("console", on_console)
        logger.info("Stopped network and console listeners.")
        
        # ── Form Detection (Before Interactive Discovery) ──
        logger.info("Scanning forms...")
        result["forms_html"] = await self._scan_forms(page)
        logger.info("Detecting forms...")
        result["forms"] = await self._detect_forms(page)

        # ── Interactive Route Discovery ──
        logger.info("Starting interactive route discovery...")
        result["interactive_routes"] = await self._discover_interactive_routes(page)
        
        if page.url != url:
            logger.info(f"Returning to original URL: {url}")
            await page.goto(url, wait_until="domcontentloaded")
            await page.wait_for_timeout(SETTLE_TIME_MS)


    async def load(self, url: str, keep_page_open: bool = False) -> Dict[str, Any]:
        if not self.context:
            raise RuntimeError("Loader not started")

        result: Dict[str, Any] = self._initial_result_dict(url)

        for attempt in range(1, RETRIES + 1):
            page: Optional[Page] = None
            try:
                page = await self.context.new_page()
                await asyncio.wait_for(self._load_page(page, url, result), timeout=MAX_LOAD_SECONDS)
                # If keep_page_open is True, store the page instead of closing it
                if keep_page_open:
                    self._keep_alive_page = page
                    page = None  # Don't close it in finally block
                return result
            except (PlaywrightError, RuntimeError) as e:
                logger.warning(f"Attempt {attempt}/{RETRIES} failed: {e}")
                result["status"] = "failed"
                result["error"] = str(e)
            except asyncio.TimeoutError:
                logger.warning(f"Attempt {attempt}/{RETRIES} timed out")
                result["status"] = "failed"
                result["error"] = "Global timeout exceeded"
            finally:
                if page:
                    await page.close()

        return result

    async def submit_form(self, url: str, form_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Loads the page, fills form data, and submits it.
        """
        if not self.context:
            raise RuntimeError("Loader not started")

        result: Dict[str, Any] = self._initial_result_dict(url)
        
        page: Optional[Page] = None
        try:
            page = await self.context.new_page()
            # 1. Load the page initially
            await page.goto(url, wait_until="networkidle", timeout=NAV_TIMEOUT_MS)
            
            # 2. Execute automation script with form_data
            if self.form_automation_script_path.exists():
                logger.info(f"Executing form automation with data: {form_data}")
                script = self.form_automation_script_path.read_text(encoding='utf-8')
                automation_result = await page.evaluate(script, form_data)
                result["form_automation_result"] = automation_result
                
                # 3. Wait for navigation or a bit of time to see what happens
                try:
                    await page.wait_for_load_state("networkidle", timeout=5000)
                except:
                    pass
                
                # 4. Capture state after submission
                result["url_after_submit"] = page.url
                result["html_after_submit"] = await page.content()
                result["visible_text_after_submit"] = await self._extract_visible_text(page)
                
            return result
        except Exception as e:
            logger.error(f"Form submission failed: {e}")
            result["error"] = str(e)
            return result
        finally:
            if page:
                await page.close()

    def _initial_result_dict(self, url: str) -> Dict[str, Any]:
        return {
            "url": url,
            "final_url": None,
            "http_status": None,
            "status": "pending",
            "navigation_time_seconds": None,
            "load_time_seconds": None,
            "error": None,
            "html": None,
            "visible_text": None,
            "network_requests": [],
            "console_errors": [],
            "layout_snapshot_desktop": None,
            "layout_snapshot_mobile": None,
            "discovered_urls": [],
            "interactive_routes":[],
            "forms_html": [],
            "forms": [],
        }


# ──────────────────────────────────────────────
# Runner
# ──────────────────────────────────────────────
async def main():
    loader = PageLoader(headless=False)
    await loader.start()
    # Load with keep_page_open=True to prevent browser from closing
    result = await loader.load("https://practice.qabrains.com/", keep_page_open=True)

    import json
    Path("result.json").write_text(json.dumps(result, indent=2))

    from url_verifier import URLVerifier
    verifier = URLVerifier()
    report = verifier.verify(url=result["url"], final_url=result["final_url"], http_status=result["http_status"], status=result["status"], navigation_time=result["navigation_time_seconds"], load_time=result["load_time_seconds"], error=result["error"], console_errors=result["console_errors"])
    verifier.print_report(report)
    
    # Keep loader alive until stop() is explicitly called
    logger.info("Loader is ready. Browser window will stay open until stop() is called.")
    
    # Wait for user input asynchronously (to avoid blocking the event loop)
    # Using run_in_executor to run the blocking input() call without blocking the async event loop
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, input, "Press Enter to stop the loader...")
    
    # User pressed Enter, stop the loader
    logger.info("Stopping loader...")
    await loader.stop()


if __name__ == "__main__":
    asyncio.run(main())
