import json
import logging
from pathlib import Path
from typing import List, Dict, Any

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [%(levelname)s] - [REPORT_GEN] - %(message)s'
)
logger = logging.getLogger(__name__)

class ReportGenerator:
    """
    Handles merging of crawl_results.json and llm_results.json into dual reports.
    """

    def __init__(
        self, 
        crawl_path: str = "crawl_results.json", 
        llm_path: str = "llm_results.json"
    ):
        self.crawl_path = Path(crawl_path)
        self.llm_path = Path(llm_path)

    def _load_crawl_results(self) -> List[Dict[str, Any]]:
        """Parses multiple concatenated JSON objects from the results file."""
        if not self.crawl_path.exists():
            logger.error(f"Crawl results not found: {self.crawl_path}")
            return []

        results = []
        try:
            content = self.crawl_path.read_text(encoding='utf-8')
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

    def _load_llm_results(self) -> List[Dict[str, Any]]:
        """Loads the standard JSON list from llm_results.json."""
        if not self.llm_path.exists():
            logger.warning(f"LLM results common not found: {self.llm_path}")
            return []
        try:
            with open(self.llm_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load LLM results: {e}")
            return []

    def generate(self):
        logger.info("🚀 Generating final reports...")
        
        crawl_data = self._load_crawl_results()
        llm_data = self._load_llm_results()
        
        # 1. Full Merge Report
        final_report = []
        brief_report = {
            "failed_pages": [],
            "form_qa_errors": [],
            "llm_qa_issues": [],
            "poor_layout_health": []
        }
        
        # Index LLM lookup
        llm_lookup = {res["url"]: res for res in llm_data if "url" in res}
        
        for page in crawl_data:
            url = page.get("final_url") or page.get("url")
            merged_page = page.copy()
            
            # --- FULL REPORT MERGE ---
            llm_res = llm_lookup.get(url)
            if llm_res:
                merged_page["llm_analysis"] = llm_res
            else:
                # User request: "if not use the visible text from the loader instead in reports"
                # visible_text is already in 'merged_page'.
                # We can add a simple flag for clarity.
                merged_page["llm_analysis"] = {
                    "status": "skipped",
                    "reason": "LLM validation was disabled or no data available",
                    "raw_text_preview": (page.get("visible_text", "")[:200] + "...") if page.get("visible_text") else "No text found"
                }
            final_report.append(merged_page)
            
            # --- BRIEF REPORT logic ---
            
            # Category 1: Non-200 Status
            if page.get("http_status") != 200 or page.get("status") != "success":
                brief_report["failed_pages"].append({
                    "url": url,
                    "status_code": page.get("http_status"),
                    "page_status": page.get("status")
                })
            
            # Category 2: Form QA Errors (Console messages)
            form_qa = page.get("form_qa") or []
            for f_res in form_qa:
                form_has_err = False
                for test in f_res.get("tests", []):
                    if test.get("has_errors"):
                        brief_report["form_qa_errors"].append({
                            "url": url,
                            "form_id": f_res.get("form", {}).get("id"),
                            "console_logs": [log["text"] for log in test.get("console_logs", []) if "text" in log]
                        })
                        form_has_err = True
                        break 
                if form_has_err: break
            
            # Category 3: LLM Issues
            if llm_res:
                if not llm_res.get("passed_basic_qa") or llm_res.get("overall_quality") in ("poor", "broken"):
                    brief_report["llm_qa_issues"].append({
                        "url": url,
                        "llm_report": llm_res
                    })
            
            # Category 4: Poor Layout Health (< 50%)
            layout_report = page.get("layout_report", {})
            score = layout_report.get("health_score", 100)
            if score < 50:
                brief_report["poor_layout_health"].append({
                    "url": url,
                    "health_score": score,
                    "layout_summary": layout_report.get("summary")
                })

        # Save Final Full Report
        with open("final_qa_report.json", "w", encoding="utf-8") as f:
            json.dump(final_report, f, indent=4)
            
        # Save Brief Report
        with open("brief_qa_report.json", "w", encoding="utf-8") as f:
            json.dump(brief_report, f, indent=4)
            
        logger.info(f"✅ Generated final_qa_report.json (items: {len(final_report)})")
        logger.info(f"✅ Generated brief_qa_report.json")

if __name__ == "__main__":
    generator = ReportGenerator()
    generator.generate()
