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
    QA-grade Playwright page loader with form detection & basic automated testing.
    """

    def __init__(
        self,
        headless: bool = True,
        timeout: int = 30000,
        settle_time_ms: int = 1000,
        test_forms: bool = False,
        real_submits: bool = False,
        max_forms: int = 5,
    ):
        self.headless = headless
        self.timeout = timeout
        self.settle_time_ms = settle_time_ms
        self.test_forms = test_forms
        self.real_submits = real_submits
        self.max_forms = max_forms
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
        self.form_detection_path = Path("discovery/form_detection.js")
        self.config_path = Path("discovery/form_test_cases.json")

        # Load test configuration
        self.test_config = {}
        if self.config_path.exists():
            try:
                with open(self.config_path, 'r') as f:
                    self.test_config = json.load(f)
            except Exception as e:
                logger.error(f"Failed to load form test config: {e}")

        self.test_cases = self.test_config.get("strategies", [
            {"name": "all_valid", "description": "Fill with plausible values"},
            {"name": "all_blank", "description": "Leave everything empty"},
            {"name": "exceed_length", "description": "Put very long text in fields"},
            {"name": "wrong_type", "description": "Deliberately use incorrect data formats"}
        ])

        if self.real_submits:
            logger.warning("⚠️  REAL FORM SUBMISSIONS ENABLED – be very careful!")

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
    # FORM QA – Detection & Testing
    # ─────────────────────────────────────────────────────────────
    async def _detect_forms(self, page: Page) -> List[Dict[str, Any]]:
        """Inject form detection script and return discovered forms"""
        if not self.form_detection_path.exists():
            logger.error("form_detection.js not found – skipping form QA")
            return []

        try:
            script = self.form_detection_path.read_text(encoding="utf-8")
            await page.evaluate(script)
            detected = await page.evaluate("() => window.detectForms()")
            return detected[:self.max_forms]
        except Exception as e:
            logger.error(f"Form detection failed: {e}")
            return []

    async def _run_tests_on_form(self, page: Page, form: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Execute test cases on a single form"""
        if not form.get('submitSelectors'):
            return [{"test_type": "skipped", "reason": "No submit button detected"}]

        results = []
        submit_selector = form['submitSelectors'][0]  # Use top-ranked button

        # Temporary listeners for this form
        test_console = []
        test_network = []

        def capture_console(msg: ConsoleMessage):
            if msg.type in ("error", "warning"):
                test_console.append({
                    "type": msg.type,
                    "text": msg.text,
                    "location": msg.location
                })

        def capture_response(resp: Response):
            if resp.request.method in ("POST", "PUT", "PATCH"):
                test_network.append({
                    "url": resp.url,
                    "status": resp.status,
                    "method": resp.request.method
                })

        page.on("console", capture_console)
        page.on("response", capture_response)

        # Track new pages/tabs
        new_pages = []

        async def handle_new_page(p):
            new_pages.append(p)
            p.on("console", capture_console)
            p.on("response", capture_response)

        page.context.on("page", handle_new_page)

        try:
            for case in self.test_cases:
                # Ensure we're on the correct page before each test
                if self.current_page_url and page.url != self.current_page_url:
                    logger.info(f"URL changed. Returning to {self.current_page_url}...")
                    try:
                        await page.goto(self.current_page_url, wait_until="domcontentloaded", timeout=10000)
                        await page.wait_for_timeout(500)
                    except Exception as e:
                        logger.error(f"Failed to return to page: {e}")

                test_name = case["name"]
                test_console.clear()
                test_network.clear()

                # Reset form
                try:
                    await page.evaluate(f"""() => {{
                        const c = document.querySelector('{form["containerSelector"]}');
                        const f = c.closest('form') || c;
                        if (f && f.reset) f.reset();
                    }}""")
                except:
                    pass

                # Fill fields according to test case
                filled = {}
                field_types_config = self.test_config.get("field_types", {})
                
                for field in form.get('fields', []):
                    sel = field['selector']
                    tag_name = field.get('tagName', 'input')
                    type_hint = field.get('typeHint', field.get('type', 'text'))
                    
                    try:
                        if tag_name == 'select':
                            # Handle dropdowns
                            options = field.get('options', [])
                            if options:
                                import random
                                chosen = random.choice(options)
                                await page.locator(sel).select_option(value=chosen['value'])
                                filled[sel] = chosen['text']
                                await page.wait_for_timeout(100)
                        else:
                            # Regular input/textarea
                            type_config = field_types_config.get(type_hint, field_types_config.get('text', {}))
                            value = type_config.get(test_name, "")
                            
                            await page.locator(sel).fill(str(value))
                            filled[sel] = value
                            await page.locator(sel).blur()
                            await page.wait_for_timeout(50)
                    except Exception as fill_err:
                        logger.debug(f"Could not fill {sel}: {fill_err}")

                # Submit and capture results
                ui_warnings = []
                orig_url = page.url
                did_navigate = False
                new_tab_url = None
                new_url = None

                try:
                    if self.real_submits:
                        # Strategy 1: Click Submit Button
                        clicked = False
                        if submit_selector:
                            try:
                                async with page.expect_response(lambda r: True, timeout=5000):
                                    await page.locator(submit_selector).click(timeout=3000)
                                clicked = True
                            except:
                                pass
                        
                        # Strategy 2: Fallback to "Enter" on last field
                        if not clicked and filled:
                            try:
                                last_field = list(filled.keys())[-1]
                                logger.info(f"Fallback: Pressing Enter on {last_field}")
                                await page.locator(last_field).press("Enter")
                                await page.wait_for_timeout(1500)
                            except Exception as e:
                                logger.debug(f"Fallback failed: {e}")

                    else:
                        # Simulate validation without actual submit
                        if submit_selector:
                            await page.locator(submit_selector).click(force=True, timeout=3000)

                    await page.wait_for_timeout(1000)

                    # Check for new tabs
                    if new_pages:
                        logger.info(f"Detected {len(new_pages)} new tab(s)")
                        for p in new_pages:
                            try:
                                new_tab_url = p.url
                                await p.wait_for_load_state("domcontentloaded", timeout=3000)
                                await p.close()
                            except Exception as p_err:
                                logger.debug(f"Error handling new tab: {p_err}")
                        new_pages.clear()

                    # Check for navigation
                    target_url = self.current_page_url if self.current_page_url else orig_url
                    if page.url != target_url:
                        new_url = page.url
                        did_navigate = True
                        logger.info(f"Page navigated from {target_url} to {page.url}")
                        try:
                            await page.goto(target_url, wait_until="domcontentloaded", timeout=5000)
                            await page.wait_for_timeout(500)
                        except Exception as nav_err:
                            logger.error(f"Failed to return to original page: {nav_err}")

                    # Collect visible errors - try multiple times with delays
                    try:
                        # Wait a bit more for any async validation to complete
                        await page.wait_for_timeout(500)
                        
                        ui_warnings = await page.evaluate(f"""() => {{
                            if (window.detectValidationErrors) {{
                                return window.detectValidationErrors('{form["containerSelector"]}');
                            }}
                            return [];
                        }}""")
                        
                        # If no errors found, try again (some frameworks are slow)
                        if not ui_warnings:
                            await page.wait_for_timeout(500)
                            ui_warnings = await page.evaluate(f"""() => {{
                                if (window.detectValidationErrors) {{
                                    return window.detectValidationErrors('{form["containerSelector"]}');
                                }}
                                return [];
                            }}""")
                    except Exception as e:
                        logger.debug(f"UI Error Check failed: {e}")

                except Exception as action_err:
                    test_console.append({"type": "action_error", "text": str(action_err)})
                current_url_after_action = page.url if did_navigate else None

                results.append({
                    "test_case": test_name,
                    "description": case["description"],
                    "filled_values": filled,
                    "console_logs": test_console.copy(),
                    "network_activity": test_network.copy(),
                    "ui_warnings": ui_warnings,
                    "did_navigate": did_navigate,
                    "new_tab_url": new_tab_url,
                    "new_url": new_url if new_url else None,  # URL after navigation
                    "has_errors": bool(test_console or ui_warnings or any(r.get('status', 200) >= 400 for r in test_network)),
                })

                await page.wait_for_timeout(300)

        finally:
            # Clean up listeners
            page.context.remove_listener("page", handle_new_page)
            page.remove_listener("console", capture_console)
            page.remove_listener("response", capture_response)

        return results

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

            "form_qa": None,
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

            # ── FORM QA ────────────────────────────────
            if self.test_forms:
                # Remove global listeners to avoid cluttering main logs
                try:
                    page.remove_listener("response", on_response)
                    page.remove_listener("console", on_console)
                except Exception:
                    pass

                logger.info("Running form QA tests...")
                detected_forms = await self._detect_forms(page)

                form_results = []
                for form in detected_forms:
                    tests = await self._run_tests_on_form(page, form)
                    form_results.append({
                        "form": {
                            "id": form.get("id"),
                            "container": form.get("containerSelector"),
                            "action": form.get("action"),
                            "method": form.get("method"),
                            "field_count": len(form.get("fields", [])),
                        },
                        "tests": tests
                    })

                result["form_qa"] = form_results

                # Reattach listeners
                page.on("response", on_response)
                page.on("console", on_console)

        except Exception as e:
            logger.error(f"Critical load failure: {e}")
            result["status"] = "failed"
            result["error"] = str(e)

        finally:
            if page:
                await page.close()

        return result


async def main():
    loader = PageLoader(headless=False, test_forms=True, real_submits=True)
    await loader.start()
    try:
        result = await loader.load_and_capture("https://practice.qabrains.com/registration")
        with open("result.json", "w") as f:
            json.dump(result, f, indent=2)
    finally:
        await loader.stop()

if __name__ == "__main__":
    asyncio.run(main())