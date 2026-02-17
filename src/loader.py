import asyncio
import logging
import time
import json
from pathlib import Path
from typing import Optional, Dict, Any, List
from playwright.async_api import async_playwright, Browser, BrowserContext, Page, Error as PlaywrightError

import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from config import settings

logging.basicConfig(
    level=settings.logging_level, 
    format="%(asctime)s - [%(levelname)s] - %(name)s - %(message)s"
)
logger = logging.getLogger(__name__)


class PageLoader:
    def __init__(self, headless: Optional[bool] = None):

        self.headless = headless if headless is not None else settings.browser.headless
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None

        # Scripts directory
        self.scripts_dir = Path("src/scripts")

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
        script = self.scroll_script_path.read_text(encoding="utf-8")
        try:
            await page.evaluate(script)
        except PlaywrightError as e:
            logger.warning(f"Scroll script execution failed: {e}")

    async def _extract_visible_text(self, page: Page) -> str:
        if not self.text_script_path.exists():
            logger.warning("Text extraction script not found.")
            return ""
        script = self.text_script_path.read_text(encoding="utf-8")
        try:
            return await page.evaluate(script)
        except PlaywrightError as e:
            logger.warning(f"Text extraction failed: {e}")
            return ""

    async def _capture_layout_snapshot(self, page: Page) -> Dict[str, Any]:
        if not self.layout_snapshot_script_path.exists():
            logger.warning("Layout snapshot script not found.")
            return {}
        script = self.layout_snapshot_script_path.read_text(encoding="utf-8")
        try:
            return await page.evaluate(script)
        except PlaywrightError as e:
            logger.warning(f"Layout snapshot failed: {e}")
            return {}
    
    async def _capture_dynamic_links(self, page: Page) -> List[str]:
        if self.dynamic_links_script_path.exists():
            return await page.evaluate(self.dynamic_links_script_path.read_text(encoding="utf-8"))
        return []

    async def _discover_interactive_routes(self, page: Page):
        if self.interactive_route_discovery_path.exists():
            return await page.evaluate(self.interactive_route_discovery_path.read_text(encoding="utf-8"))
            page.wait_for_timeout(settings.browser.settle_time_ms)
        return []

    async def _scan_forms(self, page: Page):
        if self.form_html_extractor_script_path.exists():
            return await page.evaluate(self.form_html_extractor_script_path.read_text(encoding="utf-8"))
        return []

    async def _fill_forms(self, page: Page, form_payload: Dict[str, Any]) -> Dict[str, Any]:
        if not self.fill_forms_script_path.exists():
            logger.warning("Fill forms script not found.")
            return {"error": "Fill forms script not found."}
        
        # Ensure scan ran
        state_exists = await page.evaluate("() => !!window.__FORMS_STATE__")
        if not state_exists:
            return {"error": "Form state missing. scan_forms.js must run first."}

        script = self.fill_forms_script_path.read_text(encoding="utf-8")
        try:
            return await page.evaluate(script, form_payload)
        except PlaywrightError as e:
            logger.warning(f"Form filling failed: {e}")
            return {"error": str(e)}

    async def _load_page(self, page: Page, url: str, result: Dict[str, Any], deep_analysis: bool = False, form_data: Optional[Any] = None):
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
        response = await page.goto(url, wait_until="domcontentloaded", timeout=settings.browser.nav_timeout_ms)
        navigation_time = time.perf_counter() - start_time

        
        if not response:
            raise RuntimeError("No response received")

        result["final_url"] = page.url
        result["http_status"] = response.status
        result["status"] = "success" if response.ok else "failed"
        result["navigation_time_seconds"] = navigation_time

        try:
            await page.wait_for_load_state("networkidle", timeout=settings.browser.nav_timeout_ms)
            result["load_time_seconds"] = time.perf_counter() - start_time
        except PlaywrightError:
            logger.warning("networkidle not reached, continuing")
            result["load_time_seconds"] = time.perf_counter() - start_time

        if not deep_analysis:
            # Clean up listeners and exit early for minimal load
            page.remove_listener("response", on_response)
            page.remove_listener("console", on_console)
            return

        # ── Deep Analysis Blocks ──
        
        # ── Lazy-load scrolling ──
        await self._scroll_page(page)
        await page.wait_for_timeout(settings.browser.settle_time_ms)


        # ── Capture visible text, and layout snapshot ──
        result["visible_text"] = await self._extract_visible_text(page)
        #Discover urls
        result["discovered_urls"] = await self._capture_dynamic_links(page)

        # Desktop
        #----Page already in desktop mode----
        result["layout_snapshot_desktop"] = await self._capture_layout_snapshot(page)
        
        # Mobile
        mobile_vp = settings.browser.viewports["mobile"]
        await page.set_viewport_size({"width": mobile_vp.width, "height": mobile_vp.height})
        await page.wait_for_timeout(settings.browser.settle_time_ms)
        result["layout_snapshot_mobile"] = await self._capture_layout_snapshot(page)
        #-----Set back to desktop mode (Maximized)-----
        desktop_vp = settings.browser.viewports["desktop"]
        await page.set_viewport_size({"width": desktop_vp.width, "height": desktop_vp.height})
        await page.wait_for_timeout(settings.browser.settle_time_ms)


        # ── Add network & console logs ──
        result["network_requests"] = network_requests
        result["console_errors"] = console_errors

        # Explicitly remove listeners to stop tracking
        page.remove_listener("response", on_response)
        page.remove_listener("console", on_console)
        #logger.info("Stopped network and console listeners.")
        
        # ── Form Detection (Before Interactive Discovery) ──
        #logger.info("Scanning forms (canonical)...")
        scanned_forms = await self._scan_forms(page)
        result["forms_html"] = scanned_forms

        # 🔑 CRITICAL: make scan available to sibling scripts
        await page.evaluate(
            "forms => window.__FORMS_STATE__ = forms",
            scanned_forms
        )

        # ── Interactive Route Discovery ──
        #logger.info("Starting interactive route discovery...")
        result["interactive_routes"] = await self._discover_interactive_routes(page)
        
        if page.url != url:
            #logger.info(f"Returning to original URL: {url}")
            await page.goto(url, wait_until="domcontentloaded")
            await page.wait_for_timeout(settings.browser.settle_time_ms)



    async def load(self, url: str, deep_analysis: Optional[bool] = None, form_data: Optional[Any] = None, keep_open: bool = False) -> Dict[str, Any]:
        if not self.context:
            raise RuntimeError("Loader not started")

        if deep_analysis is None:
            deep_analysis = settings.browser.deep_analysis

        result: Dict[str, Any] = self._initial_result_dict(url)

        for attempt in range(1, settings.browser.retries + 1):
            page: Optional[Page] = None
            try:
                page = await self.context.new_page()
                await asyncio.wait_for(self._load_page(page, url, result, deep_analysis=deep_analysis, form_data=form_data), timeout=settings.browser.max_load_seconds)
                return result
            except (PlaywrightError, RuntimeError) as e:
                logger.warning(f"Attempt {attempt}/{settings.browser.retries} failed: {e}")
                result["status"] = "failed"
                result["error"] = str(e)
            except asyncio.TimeoutError:
                logger.warning(f"Attempt {attempt}/{settings.browser.retries} timed out")
                result["status"] = "failed"
                result["error"] = "Global timeout exceeded"

            finally:
                if page:
                    if not keep_open:
                        await page.close()
                    else:
                        self.active_page = page

        return result


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
            "network_requests": None,
            "console_errors": None,
            "layout_snapshot_desktop": None,
            "layout_snapshot_mobile": None,
            "discovered_urls": None,
            "interactive_routes": None,
            "forms_html": None,
        }



# ──────────────────────────────────────────────
# Runner
# ──────────────────────────────────────────────
async def main():
    loader = PageLoader(headless=False)
    await loader.start()
    
    url = "https://qabrains.com/"
    
    logger.info(f"Step 1: Minimal Loading: {url}")
    result = await loader.load(url, deep_analysis=True)
    with open("result.json", "w") as f:
        json.dump(result, f, indent=2)
    await loader.stop()
    
    from src.layout_validator import validate_layout
    report = validate_layout(result)
    with open("layout_validations.json", "w") as f:
        json.dump(report, f, indent=2)
    logger.info("Layout validations saved to layout_validations.json")


if __name__ == "__main__":
    asyncio.run(main())
