import asyncio
import logging
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

        # Scripts directory
        self.scripts_dir = Path("new/scripts")
        self.scroll_script_path = self.scripts_dir / "scroll_page.js"
        self.text_script_path = self.scripts_dir / "extract_visible_text.js"
        self.layout_snapshot_script_path = self.scripts_dir / "layout_snapshot.js"
        self.dynamic_links_script_path = self.scripts_dir / "dynamic_links_capture.js"
        self.interactive_route_discovery_path = self.scripts_dir / "interactive_route_discovery.js"
        self.form_detector_script_path = self.scripts_dir / "form_detector.js"

    async def start(self):
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=self.headless,
        )
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


    async def _detect_forms(self, page: Page) -> List[Dict[str, Any]]:
        if not self.form_detector_script_path.exists():
            logger.warning("Form detector script not found.")
            return []
        script = self.form_detector_script_path.read_text()
        try:
            return await page.evaluate(script)
        except PlaywrightError as e:
            logger.warning(f"Form detection failed: {e}")
            return []


    async def _load_page(self, page: Page, url: str, result: Dict[str, Any]):
        # ── Setup listeners before navigation ──
        network_requests: List[Dict[str, Any]] = []
        console_errors: List[Dict[str, Any]] = []

        page.on("response", lambda r: network_requests.append({
            "url": r.url,
            "status": r.status,
            "method": r.request.method,
            "resource_type": r.request.resource_type
        }))

        page.on("console", lambda m: (
            m.type in ("error", "warning") and
            console_errors.append({
                "type": m.type,
                "text": m.text,
                "location": m.location
            })
        ))

        # ── Navigate ──
        response = await page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
        if not response:
            raise RuntimeError("No response received")

        result["final_url"] = page.url
        result["http_status"] = response.status
        result["status"] = "success" if response.ok else "failed"

        try:
            await page.wait_for_load_state("networkidle", timeout=NAV_TIMEOUT_MS)
        except PlaywrightError:
            logger.warning("networkidle not reached, continuing")

        # ── Lazy-load scrolling ──
        await self._scroll_page(page)
        await page.wait_for_timeout(SETTLE_TIME_MS)

        # ── Capture HTML, visible text, and layout snapshot ──
        result["html"] = await page.content()
        result["visible_text"] = await self._extract_visible_text(page)
        result["layout_snapshot"] = await self._capture_layout_snapshot(page)
        result["discovered_urls"] = await self._capture_dynamic_links(page)
        
        # ── Form Detection (Before Interactive Discovery) ──
        logger.info("Detecting forms...")
        result["forms"] = await self._detect_forms(page)

        # ── Interactive Route Discovery ──
        logger.info("Starting interactive route discovery...")
        result["interactive_routes"] = await self._discover_interactive_routes(page)
        
        if page.url != url:
            logger.info(f"Returning to original URL: {url}")
            await page.goto(url, wait_until="domcontentloaded")
            await page.wait_for_timeout(SETTLE_TIME_MS)

        # ── Add network & console logs ──
        result["network_requests"] = network_requests
        result["console_errors"] = console_errors
        

        

    async def load(self, url: str) -> Dict[str, Any]:
        if not self.context:
            raise RuntimeError("Loader not started")

        result: Dict[str, Any] = {
            "url": url,
            "final_url": None,
            "http_status": None,
            "status": "pending",
            "error": None,
            "html": None,
            "visible_text": None,
            "network_requests": [],
            "console_errors": [],
            "layout_snapshot": None,
            "discovered_urls": [],
            "interactive_routes":[],
            "forms": [],
        }

        for attempt in range(1, RETRIES + 1):
            page: Optional[Page] = None
            try:
                page = await self.context.new_page()
                await asyncio.wait_for(self._load_page(page, url, result), timeout=MAX_LOAD_SECONDS)
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


# ──────────────────────────────────────────────
# Runner
# ──────────────────────────────────────────────
async def main():
    loader = PageLoader(headless=False)
    await loader.start()
    result = await loader.load("https://practice.qabrains.com/registration")
    await loader.stop()

    import json
    Path("result.json").write_text(json.dumps(result, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
