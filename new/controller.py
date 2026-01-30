import asyncio
import json
import logging
import sys
import urllib.parse
from pathlib import Path
from typing import List, Set, Dict, Any
from urllib.parse import urlparse


from loader import PageLoader
from extractor import clean_and_filter_urls
from url_classifier import URLClassifier, URLCategory

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - [%(levelname)s] - %(message)s")
logger = logging.getLogger(__name__)

class CrawlController:
    def __init__(self, start_url: str, max_workers: int = 3):
        self.start_url = self.normalize_url(start_url)
        self.max_workers = max_workers
        self.visited_urls: Set[str] = set()
        self.queued_urls: Set[str] = set()
        self.queue: asyncio.Queue = asyncio.Queue()
        self.loader = PageLoader(headless=False)
        self.classifier = URLClassifier(target_domain=self.start_url)
        self.results: Dict[str, Any] = {}
        self.lock = asyncio.Lock()

    def normalize_url(self, url: str) -> str:
        """Strips fragments and trailing slashes for consistent comparison."""
        try:
            parsed = urlparse(url)
            # Normalize scheme and netloc to lowercase, remove fragment, strip trailing slash from path
            clean_path = parsed.path.rstrip('/')
            return urllib.parse.urlunparse(parsed._replace(fragment='', path=clean_path, query=parsed.query))
        except Exception:
            return url

    async def _process_url(self, url: str):
        """Processes a single URL: loads, extracts, and classifies."""
        normalized_url = self.normalize_url(url)
        async with self.lock:
            if normalized_url in self.visited_urls:
                return
            self.visited_urls.add(normalized_url)
        
        logger.info(f"Crawling: {normalized_url}")
        try:
            # Load page
            result = await self.loader.load(normalized_url)
            
            # Store full result
            async with self.lock:
                self.results[normalized_url] = result
                # Save whole result in the file incrementally
                Path("crawl_summary.json").write_text(json.dumps(self.results, indent=4))


            # Extract and Clean URLs
            discovered_urls_data = result.get("discovered_urls", {})
            interactive_routes_data = result.get("interactive_routes", {})
            network_requests = result.get("network_requests", [])
        
            # Pull URL strings from all sources
            discovered_urls = discovered_urls_data.get("urls", []) if isinstance(discovered_urls_data, dict) else []
            interactive_routes = interactive_routes_data.get("urls", []) if isinstance(interactive_routes_data, dict) else []
            network_urls = [req["url"] for req in network_requests if isinstance(req, dict) and "url" in req]
            
            combined_raw = list(set(discovered_urls + interactive_routes + network_urls))
            cleaned_urls = clean_and_filter_urls(combined_raw, base_url=normalized_url)

            # Classify Discovered URLs
            classification_map = self.classifier.categorize_list(cleaned_urls)
            
            new_pages = []
            for u, data in classification_map.items():
                if data["category"] == URLCategory.PAGE.value:
                    norm_u = self.normalize_url(u)
                    # Check if it's the same domain
                    if self.classifier._is_internal(urlparse(norm_u).netloc):
                        new_pages.append(norm_u)

            # Add new pages to queue
            for page_url in new_pages:
                async with self.lock:
                    if page_url not in self.visited_urls and page_url not in self.queued_urls:
                        await self.queue.put(page_url)
                        self.queued_urls.add(page_url)
                        logger.debug(f"Queued new page: {page_url}")

        except Exception as e:
            logger.error(f"Error crawling {normalized_url}: {e}")

    async def worker(self):
        """Worker task to process URLs from the queue."""
        while True:
            url = await self.queue.get()
            try:
                await self._process_url(url)
            finally:
                self.queue.task_done()

    async def run(self):
        """Starts the crawling process."""
        await self.loader.start()
        await self.queue.put(self.start_url)
        self.queued_urls.add(self.start_url)
        
        # Create worker tasks
        workers = [asyncio.create_task(self.worker()) for _ in range(self.max_workers)]
        
        # Wait for all tasks to be finished
        await self.queue.join()
        
        # Stop workers
        for w in workers:
            w.cancel()
        
        await asyncio.gather(*workers, return_exceptions=True)
        await self.loader.stop()
        
        # Save summary of results
        Path("crawl_summary.json").write_text(json.dumps(self.results, indent=4))


        logger.info(f"Crawl complete. Visited {len(self.visited_urls)} URLs.")
        logger.info("--- Discovered Pages (Visited) ---")
        for u in sorted(list(self.visited_urls)):
            print(u)

if __name__ == "__main__":
    import urllib.parse  # Ensure it matches normalized usage
    asyncio.run(CrawlController("https://practice.qabrains.com/", max_workers=5).run())

    
