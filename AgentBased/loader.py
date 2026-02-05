import asyncio
import logging
import time
from pathlib import Path
from typing import Optional, Dict, Any, List
from playwright.async_api import async_playwright, Browser, BrowserContext, Page, Error as PlaywrightError
import json


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

        # Scripts directory
        self.scripts_dir = Path("AgentBased/scripts")
        self.scroll_script_path = self.scripts_dir / "scroll_page.js"
        self.text_script_path = self.scripts_dir / "extract_visible_text.js"
        self.layout_snapshot_script_path = self.scripts_dir / "layout_snapshot.js"
        self.dynamic_links_script_path = self.scripts_dir / "dynamic_links_capture.js"
        self.interactive_route_discovery_path = self.scripts_dir / "interactive_route_discovery.js"
        self.form_html_extractor_script_path = self.scripts_dir / "scan_forms.js"
        self.fill_forms_script_path = self.scripts_dir / "fill_forms.js"
        self.active_page: Optional[Page] = None

    async def start(self):
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=self.headless)
        self.context = await self.browser.new_context(ignore_https_errors=True) 
        
    async def stop(self):
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()

    async def _scroll_page(self, page: Page):
        if not self.scroll_script_path.exists():
            logger.warning("Scroll script not found, skipping scroll.")
            return
        script = self.scroll_script_path.read_text()
        try:
            await page.evaluate(script)
        except PlaywrightError as e:
            logger.warning(f"Scroll script execution failed: {e}")

    async def _extract_visible_text(self, page: Page) -> str:
        if not self.text_script_path.exists():
            logger.warning("Text extraction script not found.")
            return ""
        script = self.text_script_path.read_text()
        try:
            return await page.evaluate(script)
        except PlaywrightError as e:
            logger.warning(f"Text extraction failed: {e}")
            return ""

    async def _capture_layout_snapshot(self, page: Page) -> Dict[str, Any]:
        if not self.layout_snapshot_script_path.exists():
            logger.warning("Layout snapshot script not found.")
            return {}
        script = self.layout_snapshot_script_path.read_text()
        try:
            return await page.evaluate(script)
        except PlaywrightError as e:
            logger.warning(f"Layout snapshot failed: {e}")
            return {}
    
    async def _capture_dynamic_links(self, page: Page) -> List[str]:
        if self.dynamic_links_script_path.exists():
            return await page.evaluate(self.dynamic_links_script_path.read_text())
        return []

    async def _discover_interactive_routes(self, page: Page):
        if self.interactive_route_discovery_path.exists():
            return await page.evaluate(self.interactive_route_discovery_path.read_text())
            page.wait_for_timeout(SETTLE_TIME_MS)
        return []
    async def _scan_forms(self, page: Page):
        if self.form_html_extractor_script_path.exists():
            return await page.evaluate(self.form_html_extractor_script_path.read_text())
        return []

    async def _fill_forms(self, page: Page, form_payload: Dict[str, Any]) -> Dict[str, Any]:
        if not self.fill_forms_script_path.exists():
            logger.warning("Fill forms script not found.")
            return {"error": "Fill forms script not found."}
        
        # Ensure scan ran
        state_exists = await page.evaluate("() => !!window.__FORMS_STATE__")
        if not state_exists:
            return {"error": "Form state missing. scan_forms.js must run first."}

        script = self.fill_forms_script_path.read_text()
        try:
            return await page.evaluate(script, form_payload)
        except PlaywrightError as e:
            logger.warning(f"Form filling failed: {e}")
            return {"error": str(e)}

    async def _load_page(self, page: Page, url: str, result: Dict[str, Any], form_data: Optional[Any] = None):
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

        # ── Capture visible text, and layout snapshot ──
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
        logger.info("Scanning forms (canonical)...")
        scanned_forms = await self._scan_forms(page)
        result["forms_html"] = scanned_forms

        # 🔑 CRITICAL: make scan available to sibling scripts
        await page.evaluate(
            "forms => window.__FORMS_STATE__ = forms",
            scanned_forms
        )

        # ── Interactive Route Discovery ──
        logger.info("Starting interactive route discovery...")
        result["interactive_routes"] = await self._discover_interactive_routes(page)
        
        if page.url != url:
            logger.info(f"Returning to original URL: {url}")
            await page.goto(url, wait_until="domcontentloaded")
            await page.wait_for_timeout(SETTLE_TIME_MS)

        # ── Form Filling ──
        if form_data:
            logger.info(f"Form data provided, filling forms in the same session...")
            
            # ── Setup listeners for submission tracking ──
            submit_network_requests: List[Dict[str, Any]] = []
            submit_console_errors: List[Dict[str, Any]] = []

            def on_submit_response(r):
                submit_network_requests.append({
                    "url": r.url,
                    "status": r.status,
                    "method": r.request.method,
                    "resource_type": r.request.resource_type
                })

            def on_submit_console(m):
                if m.type in ("error", "warning"):
                    submit_console_errors.append({
                        "type": m.type,
                        "text": m.text,
                        "location": m.location
                    })

            page.on("response", on_submit_response)
            page.on("console", on_submit_console)
            
            try:
                # Resolve form_data if it's a path
                if isinstance(form_data, (str, Path)):
                    import json
                    form_payload = json.loads(Path(form_data).read_text())
                else:
                    form_payload = form_data

                fill_result = await self._fill_forms(page, form_payload)
                result["form_fill_result"] = fill_result
                
                # Wait for potential navigation after submission
                try:
                    await page.wait_for_load_state("networkidle", timeout=5000)
                except:
                    pass
                
                logger.info(f"Form submitted. New URL: {page.url}")
            finally:
                # ── Stop listeners and save logs ──
                page.remove_listener("response", on_submit_response)
                page.remove_listener("console", on_submit_console)
                result["form_submit_network_requests"] = submit_network_requests
                result["form_submit_console_errors"] = submit_console_errors
                logger.info("Stopped submission listeners.")


    async def load(self, url: str, form_data: Optional[Any] = None, keep_open: bool = False) -> Dict[str, Any]:
        if not self.context:
            raise RuntimeError("Loader not started")

        result: Dict[str, Any] = self._initial_result_dict(url)

        for attempt in range(1, RETRIES + 1):
            page: Optional[Page] = None
            try:
                page = await self.context.new_page()
                await asyncio.wait_for(self._load_page(page, url, result, form_data=form_data), timeout=MAX_LOAD_SECONDS)
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
                    if not keep_open:
                        await page.close()
                    else:
                        self.active_page = page

        return result

    async def fill_active_page(self, form_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Fills forms on the currently active page (self.active_page) using the provided data dictionary.
        Does NOT trigger a new navigation.
        """
        if not self.active_page:
            return {"error": "No active page found. Call load(..., keep_open=True) first."}

        form_result = {"url_before_fill": self.active_page.url}
        
        # ── Setup listeners for submission tracking ──
        submit_network_requests: List[Dict[str, Any]] = []
        submit_console_errors: List[Dict[str, Any]] = []

        def on_submit_response(r):
            submit_network_requests.append({
                "url": r.url,
                "status": r.status,
                "method": r.request.method,
                "resource_type": r.request.resource_type
            })

        def on_submit_console(m):
            if m.type in ("error", "warning"):
                submit_console_errors.append({
                    "type": m.type,
                    "text": m.text,
                    "location": m.location
                })

        self.active_page.on("response", on_submit_response)
        self.active_page.on("console", on_submit_console)

        try:
            logger.info(f"Filling forms on page: {self.active_page.url}")
            await self._fill_forms(self.active_page, form_data)
            
            # Wait a bit for potential submission side effects
            try:
                await self.active_page.wait_for_load_state("networkidle", timeout=5000)
            except:
                pass
            
            form_result["url_after"] = self.active_page.url
            form_result["status"] = "success"
        except Exception as e:
            logger.error(f"fill_active_page failed: {e}")
            form_result["status"] = "failed"
            form_result["error"] = str(e)
        finally:
            # ── Stop listeners and save logs ──
            # Wait briefly to catch trailing logs
            await asyncio.sleep(0.5)
            
            self.active_page.remove_listener("response", on_submit_response)
            self.active_page.remove_listener("console", on_submit_console)
            
            form_result["network_requests"] = submit_network_requests
            form_result["console_errors"] = submit_console_errors
            
            logger.info(f"Captured {len(submit_network_requests)} network requests and {len(submit_console_errors)} console errors during form submission.")

        return form_result


    def _initial_result_dict(self, url: str) -> Dict[str, Any]:
        return {
            "url": url,
            "final_url": None,
            "http_status": None,
            "status": "pending",
            "navigation_time_seconds": None,
            "load_time_seconds": None,
            "error": None,
            "visible_text": None,
            "network_requests": [],
            "console_errors": [],
            "layout_snapshot_desktop": None,
            "layout_snapshot_mobile": None,
            "discovered_urls": [],
            "interactive_routes":[],
            "forms_html": [],
        }


# ──────────────────────────────────────────────
# Runner
# ──────────────────────────────────────────────
async def main():
    loader = PageLoader(headless=False)
    await loader.start()
    
    url = "https://practice.qabrains.com/registration"
    
    form_data = {
      "formIndex": 0,
      "#name": "ali",
      "#country": "Pakistan",
      "#account": "Student",
      "#email": "ali@example.com",
      "#password": "Password123",
      "#confirm_password": "Password123",
      "submitSelector": "button.whitespace-nowrap.rounded-md.font-medium.transition-all.disabled\\:pointer-events-none.disabled\\:opacity-50.\\[\\&_svg\\]\\:pointer-events-none.\\[\\&_svg\\:not\\(\\[class\\*\\=\\'size-\\'\\]\\)\\]\\:size-4.shrink-0.\\[\\&_svg\\]\\:shrink-0.outline-none.focus-visible\\:border-ring.focus-visible\\:ring-ring\\/50.focus-visible\\:ring-\\[3px\\].aria-invalid\\:ring-destructive\\/20.dark\\:aria-invalid\\:ring-destructive\\/40.aria-invalid\\:border-destructive.bg-primary.text-primary-foreground.shadow-xs.hover\\:bg-primary\\/90.h-9.px-4.py-2.has-\\[\\>svg\\]\\:px-3.btn-submit.font-oswald.text-md.uppercase.flex.items-center.gap-2.justify-center.\\!py-6.mt-4",
      "submit": True
    }
    
    logger.info(f"Step 1: Loading and scanning page: {url}")
    # Load with keep_open=True so we can fill later
    scan_result = await loader.load(url, keep_open=True)

    # Save scan result
    Path("result.json").write_text(json.dumps(scan_result, indent=2))
    logger.info("Scan finished and saved to result.json")

    # Step 2: Fill the form independently
    input("Press Enter to continue...")
    
    logger.info(f"Step 2: Filling forms independently with provided dictionary...")
    fill_result = await loader.fill_active_page(form_data)
    
    # Save fill result
    Path("fill_result.json").write_text(json.dumps(fill_result, indent=2))

    logger.info("Tasks finished. Keeping browser open... (Press Enter to stop)")
    await asyncio.get_event_loop().run_in_executor(None, input, "")
    await loader.stop()


if __name__ == "__main__":
    asyncio.run(main())
