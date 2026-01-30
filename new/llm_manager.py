import json
import asyncio
import logging
import os
from pathlib import Path
from typing import List, Dict, Any

from qa_llm import verify_page_text

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [%(levelname)s] - [LLM_MANAGER] - %(message)s'
)
logger = logging.getLogger(__name__)

class LLMManager:
    """
    Manages sequential LLM verification of crawled pages.
    Inputs: crawl_results.json
    Outputs: llm_results.json (Saves incrementally & resumes progress)
    """

    def __init__(self, crawl_results_path: str = "crawl_results.json", output_path: str = "llm_results.json"):
        self.crawl_results_path = Path(crawl_results_path)
        self.output_path = Path(output_path)

    def _load_crawl_results(self) -> List[Dict[str, Any]]:
        """Parses multiple concatenated JSON objects from the results file."""
        if not self.crawl_results_path.exists():
            logger.error(f"File not found: {self.crawl_results_path}")
            return []

        results = []
        try:
            content = self.crawl_results_path.read_text(encoding='utf-8')
            decoder = json.JSONDecoder()
            pos = 0
            while pos < len(content):
                content = content.lstrip()
                if not content: break
                try:
                    obj, index = decoder.raw_decode(content)
                    results.append(obj)
                    content = content[index:].lstrip()
                except json.JSONDecodeError:
                    break
        except Exception as e:
            logger.error(f"Failed to load crawl results: {e}")
        
        return results

    def _load_existing_results(self) -> List[Dict[str, Any]]:
        """Loads already processed results to allow resumption."""
        if not self.output_path.exists():
            return []
        try:
            with open(self.output_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Could not load existing results for resumption: {e}")
            return []

    def _save_current_results(self, results: List[Dict[str, Any]]):
        """Immediately saves current results to disk to prevent data loss."""
        try:
            # Atomic-like write (write to tmp then rename is safer, but direct is okay for this)
            with open(self.output_path, "w", encoding="utf-8") as f:
                json.dump(results, f, indent=4)
                f.flush()
                # os.fsync(f.fileno()) # Optional: force physical write
        except Exception as e:
            logger.error(f"Failed to save incremental results: {e}")

    async def run(self):
        """
        Main execution loop with resumption and real-time saves.
        """
        logger.info("🚀 Starting LLM QA Manager")
        
        # 1. Load Crawl Data
        all_pages = self._load_crawl_results()
        
        # 2. Load Existing Progress
        llm_results = self._load_existing_results()
        processed_urls = {res["url"] for res in llm_results if "url" in res}
        
        if processed_urls:
            logger.info(f"♻️ Resuming progress. Already processed {len(processed_urls)} URLs.")

        # 3. Filter for eligible pages NOT yet processed
        valid_pages = [
            p for p in all_pages 
            if p.get("http_status") == 200 
            and p.get("visible_text") 
            and (p.get("final_url") or p.get("url")) not in processed_urls
        ]
        
        logger.info(f"Loaded {len(all_pages)} total pages. {len(valid_pages)} new pages eligible for analysis.")

        if not valid_pages:
            logger.info("✅ No new pages to analyze.")
            return

        # 4. Sequential Processing (FIFO)
        for i, page in enumerate(valid_pages):
            url = page.get("final_url") or page.get("url")
            text = page.get("visible_text")
            
            logger.info(f"[{i+1}/{len(valid_pages)}] Analyzing: {url}")
            
            try:
                # Call LLM
                result = await verify_page_text(url, text)
                llm_results.append(result)
                
                # SAVE IMMEDIATELY
                self._save_current_results(llm_results)
                
                # Rate limit safety
                await asyncio.sleep(3.0) 
                
            except Exception as e:
                logger.error(f"LLM Error on {url}: {e}")
                llm_results.append({
                    "url": url,
                    "error": str(e),
                    "status": "failed"
                })
                self._save_current_results(llm_results)
                await asyncio.sleep(1.0) # Shorter wait on error

        logger.info(f"✅ LLM Analysis complete. Results saved to {self.output_path}")

if __name__ == "__main__":
    manager = LLMManager()
    asyncio.run(manager.run())
