import asyncio
import logging
import json
from pathlib import Path
from typing import Set, Dict, Any, List
from urllib.parse import urlparse

# Simple imports as requested
from loader import PageLoader
from extractor import Extractor
from url_resolver import URLResolver
from url_classifier import URLClassifier, URLCategory
from layout_evaluator import LayoutValidator
from llm_manager import LLMManager
from report_generator import ReportGenerator

# Setup Logger
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [%(levelname)s] - %(message)s'
)
logger = logging.getLogger(__name__)

class SimpleCrawlController:
    """
    A simplified BFS crawler using the PageLoader. 
    Focuses on extraction, resolution, and basic reporting.
    """

    def __init__(self, seed_url: str, max_depth: int = 1, concurrency: int = 2, run_llm: bool = False):
        self.seed_url = seed_url
        self.max_depth = max_depth
        self.concurrency = concurrency
        self.run_llm = run_llm
        
        # Core Components
        self.loader = PageLoader(headless=False)
        self.extractor = Extractor()
        
        # Fixed context for URL processing as requested previously
        self.fixed_resolver = URLResolver(seed_url)
        self.classifier = URLClassifier(target_domain=urlparse(seed_url).netloc)
        
        # BFS State
        self.queue = asyncio.Queue()
        self.visited: Set[str] = set()
        
        # Output
        self.results_file = Path("crawl_results.json")
        if self.results_file.exists():
            self.results_file.unlink()

    async def run(self):
        logger.info(f"Starting simple crawl for {self.seed_url} (depth limit: {self.max_depth})")
        
        await self.loader.start()
        
        # BFS Seed
        await self.queue.put((self.seed_url, 0))
        self.visited.add(self._normalize(self.seed_url))
        
        # Start Parallel Workers
        workers = [
            asyncio.create_task(self.worker(f"W{i}")) 
            for i in range(self.concurrency)
        ]
        
        await self.queue.join()
        
        # Cleanup
        for w in workers:
            w.cancel()
            
        await self.loader.stop()
        logger.info("Crawl complete.")

        if self.run_llm:
            # --- Pipeline Stage 2: LLM Validation ---
            logger.info("🚀 Starting LLM Validation Phase...")
            llm_mgr = LLMManager()
            await llm_mgr.run()
        else:
            logger.info("⏩ Skipping LLM Validation Phase as requested.")

        # --- Pipeline Stage 3: Report Generation ---
        logger.info("🚀 Starting Report Generation Phase...")
        generator = ReportGenerator()
        generator.generate()
        
        logger.info("✨ Full pipeline execution completed successfully.")

    async def worker(self, name: str):
        while True:
            try:
                url, depth = await self.queue.get()
                logger.info(f"[{name}] Crawling: {url} (Depth {depth})")
                
                try:
                    # 1. Load Page
                    res = await self.loader.load_and_capture(url)
                    
                    # 2. Log Result & skip discovery for failed/404
                    is_valid = res['status'] == "success" and res['http_status'] != 404
                    if not is_valid:
                        logger.warning(f"[{name}] Page failed or 404: {url} ({res.get('http_status')})")
    
                    # 3. Report Results
                    # Requirement: Include evaluated layout instead of raw snapshot
                    report = res.copy()
                    
                    if "layout_snapshot" in report:
                        snapshot = report.pop("layout_snapshot")
                        if snapshot and "error" not in snapshot:
                            validator = LayoutValidator(snapshot)
                            report["layout_report"] = validator.evaluate()
                        else:
                            report["layout_report"] = {"error": snapshot.get("error") if snapshot else "No snapshot"}

                    report["depth"] = depth
                    self._save_to_disk(report)
    
                    # 4. BFS Discovery (DOM + Network)
                    if is_valid and (self.max_depth < 0 or depth < self.max_depth):
                        # Extract from HTML
                        dom_urls = self.extractor.extract(res.get("html", "")).get("urls", [])
                        # Extract from Network Requests
                        network_urls = [req["url"] for req in res.get("requests", [])]
                        
                        combined_raw = list(set(dom_urls + network_urls))
                        
                        # Resolve using FIXED seed context
                        resolved = self.fixed_resolver.resolve(combined_raw)
                        
                        for r_url in resolved:
                            if self.classifier.classify(r_url)['category'] == URLCategory.PAGE.value:
                                norm = self._normalize(r_url)
                                # Hash list check: if not visited, add and enqueue
                                if norm not in self.visited:
                                    self.visited.add(norm)
                                    await self.queue.put((r_url, depth + 1))
                                    logger.debug(f"Enqueued: {r_url}")

                except Exception as e:
                    logger.error(f"[{name}] Worker error on {url}: {e}")
                finally:
                    self.queue.task_done()
            except asyncio.CancelledError:
                break

    def _normalize(self, url: str) -> str:
        p = urlparse(url)
        return f"{p.netloc}{p.path}".rstrip('/')

    def _save_to_disk(self, data: Dict[str, Any]):
        with open(self.results_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps(data,indent=4))

if __name__ == "__main__":
    import sys
    seed = "https://practice.qabrains.com/"
    depth = -1  # Default to infinite
    
    run_llm = False
    if len(sys.argv) > 3:
        run_llm = sys.argv[3].lower() in ("true", "1", "t", "y", "yes")
            
    asyncio.run(SimpleCrawlController(seed, max_depth=depth,concurrency=5,run_llm=run_llm).run())
