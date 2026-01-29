import json
import logging
import asyncio
import uuid
from pathlib import Path
from typing import Dict, Any, Optional, List

from playwright.async_api import (
    async_playwright,
    Page,
    Browser,
    BrowserContext,
    Response,
    ConsoleMessage
)

# ─────────────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [%(levelname)s] - %(message)s"
)
logger = logging.getLogger(__name__)


class PageLoader:
    """
    QA-grade Playwright page loader with layout snapshot capability.
    """

    def __init__(
        self,
        headless: bool = True,
        timeout: int = 30000,
        settle_time_ms: int = 1000,
    ):
        self.headless = headless
        self.timeout = timeout
        self.settle_time_ms = settle_time_ms
        self.current_page_url: Optional[str] = None

        self.user_agent = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )

        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None

        self.screenshot_dir = Path("screenshots")
        self.screenshot_dir.mkdir(exist_ok=True)

        self.layout_script_path = Path("discovery/layout_snapshot.js")

    # ─────────────────────────────────────────────────────────────
    # Lifecycle
    # ─────────────────────────────────────────────────────────────
    async def start(self):
        if self.browser:
            return

        logger.info("Starting browser...")
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=self.headless
        )

        self.context = await self.browser.new_context(
            user_agent=self.user_agent,
            viewport={"width": 1920, "height": 1080},
            ignore_https_errors=True
        )

    async def stop(self):
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()

        self.context = None
        self.browser = None
        self.playwright = None
        logger.info("Browser stopped.")

    # ─────────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────────
    async def _perform_lazy_scroll(self, page: Page, max_scrolls: int = 5):
        try:
            last_height = await page.evaluate("document.body.scrollHeight")
            for _ in range(max_scrolls):
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(1000)
                new_height = await page.evaluate("document.body.scrollHeight")
                if new_height == last_height:
                    break
                last_height = new_height
        except Exception:
            pass

    async def _capture_viewports(self, page: Page, uid: str) -> Dict[str, Optional[str]]:
        try:
            desktop = self.screenshot_dir / f"{uid}_desktop.png"
            mobile = self.screenshot_dir / f"{uid}_mobile.png"

            await page.screenshot(path=str(desktop), full_page=True)

            await page.set_viewport_size({"width": 375, "height": 812})
            await page.wait_for_timeout(200)
            await page.evaluate("window.scrollTo(0, 0)")
            await page.screenshot(path=str(mobile), full_page=True)

            await page.set_viewport_size({"width": 1920, "height": 1080})

            return {
                "desktop_screenshot": str(desktop),
                "mobile_screenshot": str(mobile)
            }

        except Exception as e:
            logger.error(f"Screenshot failed: {e}")
            return {
                "desktop_screenshot": None,
                "mobile_screenshot": None
            }

    async def _capture_layout_snapshot(self, page: Page) -> Dict[str, Any]:
        if not self.layout_script_path.exists():
            return {"error": "layout_snapshot.js not found"}

        try:
            script = self.layout_script_path.read_text(encoding="utf-8")
            snapshot = await page.evaluate(script)
            return snapshot
        except Exception as e:
            logger.error(f"Layout snapshot failed: {e}")
            return {"error": str(e)}

    # ─────────────────────────────────────────────────────────────
    # Core API
    # ─────────────────────────────────────────────────────────────
    async def load_and_capture(
        self,
        url: str,
        take_screenshots: bool = False
    ) -> Dict[str, Any]:

        if not self.context:
            raise RuntimeError("Loader not started")

        uid = uuid.uuid4().hex[:8]

        result = {
            "url": url,
            "final_url": None,
            "http_status": None,
            "status": "pending",
            "error": None,

            "html": None,
            "visible_text": "",
            "layout_snapshot": None,

            "requests": [],
            "console_logs": [],

            "desktop_screenshot": None,
            "mobile_screenshot": None,
        }

        page: Optional[Page] = None

        try:
            page = await self.context.new_page()

            # ── Global Listeners ─────────────────────────────
            def on_response(resp: Response):
                result["requests"].append({
                    "url": resp.url,
                    "status": resp.status,
                    "method": resp.request.method,
                    "resource_type": resp.request.resource_type
                })

            def on_console(msg: ConsoleMessage):
                if msg.type in ("error", "warning"):
                    result["console_logs"].append({
                        "type": msg.type,
                        "text": msg.text,
                        "location": msg.location
                    })

            page.on("response", on_response)
            page.on("console", on_console)

            # ── Navigation ────────────────────────────
            logger.info(f"Loading {url}")
            response = await page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=self.timeout
            )

            if not response:
                result["status"] = "failed"
                result["error"] = "No response"
                result.update(await self._capture_viewports(page, uid))
                return result

            result["http_status"] = response.status
            result["final_url"] = page.url
            self.current_page_url = page.url

            if not response.ok:
                result["status"] = "failed"
                result["error"] = f"HTTP {response.status}"
                result.update(await self._capture_viewports(page, uid))
                
            else:
                result["status"] = "success"

            # ── Stabilize page ─────────────────────────────
            await page.wait_for_timeout(self.settle_time_ms)
            await self._perform_lazy_scroll(page)
            await page.wait_for_timeout(800)
            await page.evaluate("window.scrollTo(0, 0)")
            await page.wait_for_timeout(300)

            # ── Capture core data ─────────────────
            result["html"] = await page.content()

            try:
                result["visible_text"] = (
                    await page.locator("body").inner_text()
                ).strip()
            except Exception:
                pass

            result["layout_snapshot"] = await self._capture_layout_snapshot(page)

            if take_screenshots:
                result.update(await self._capture_viewports(page, uid))

        except Exception as e:
            logger.error(f"Critical load failure: {e}")
            result["status"] = "failed"
            result["error"] = str(e)

        finally:
            if page:
                await page.close()

        return result


async def main():
    loader = PageLoader(headless=False)
    await loader.start()
    try:
        target_url = "https://practice.qabrains.com/"
        result = await loader.load_and_capture(target_url)
        with open("result.json", "w") as f:
            json.dump(result, f, indent=2)
        
        from extractor import RawURLExtractor
        extractor = RawURLExtractor()
        extracted_data = extractor.extract(result["html"])
        with open("extracted_data.json", "w") as f:
            json.dump(extracted_data, f, indent=4)

    finally:
        await loader.stop()

if __name__ == "__main__":
    asyncio.run(main())