import asyncio
import json
from collections import deque
from loader import PageLoader
from url_verifier import URLVerifier
from qa_llm import verify_page_text
from layout_validator import LayoutValidator

async def main():
    # Initialize Queue and Hash Set (Deduplication)
    url_queue = deque()
    seen_urls = set()

    # Load Page
    loader = PageLoader()
    await loader.start()
    
    start_url = "https://practice.qabrains.com/"
    seen_urls.add(start_url) # Mark start URL as seen
    result = await loader.load(start_url)
    await loader.stop()

    # Verify URL Results
    verifier = URLVerifier()
    report = verifier.verify(
        url=result["url"], 
        final_url=result["final_url"], 
        http_status=result["http_status"], 
        status=result["status"], 
        navigation_time=result["navigation_time_seconds"], 
        load_time=result["load_time_seconds"], 
        error=result["error"], 
        console_errors=result["console_errors"]
    )
    verifier.print_report(report)

    # Verify Page Text
    try:
        #text_result = await verify_page_text(url=result["url"], visible_text=result["visible_text"])
        #print("\nPage Text Verification:")
        #print(json.dumps(text_result, indent=2))
        with open("text.txt", "w") as f:
            f.write(result["visible_text"])
    except Exception as e:
        print(f"\nPage Text Verification Failed: {e}")

    # Collect URLs from different sources
    discovered_data = result.get("discovered_urls", {})
    discovered_urls = discovered_data if isinstance(discovered_data, list) else []
    
    interactive_data = result.get("interactive_routes", {})
    interactive_urls = interactive_data.get("urls", []) if isinstance(interactive_data, dict) else []
    
    network_reqs = [
        req["url"] for req in result.get("network_requests", [])
        if req.get("resource_type") == "document"
    ]

    all_found_urls = discovered_urls + interactive_urls + network_reqs

    # Add to FIFO Queue with Hash-based Deduplication
    added_count = 0
    for url in all_found_urls:
        if url and url not in seen_urls:
            seen_urls.add(url)
            url_queue.append(url)
            added_count += 1

    print(f"\n--- URL Queue Status ---")
    print(f"Total Unique URLs Discovered: {len(seen_urls)}")
    print(f"URLs Added to Queue: {added_count}")
    print(f"Queue Size: {len(url_queue)}")
    
    if url_queue:
        print("\nURLs in Queue:")
        for url in url_queue:
            print(url)

        # Layout Validation
    print("\nRunning Layout Validation...")
    validator = LayoutValidator()
    if result.get("layout_snapshot_desktop"):
        validator.validate_snapshot(result["layout_snapshot_desktop"], "desktop")
    if result.get("layout_snapshot_mobile"):
        validator.validate_snapshot(result["layout_snapshot_mobile"], "mobile")
    
    validator.print_detailed_report()
    
    # Save validation report
    with open("validation_report.json", "w") as f:
        json.dump(validator.generate_report(), f, indent=2)


if __name__ == "__main__":
    asyncio.run(main())