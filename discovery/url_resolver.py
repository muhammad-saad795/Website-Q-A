import logging
from urllib.parse import urljoin
from typing import List

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [%(levelname)s] - %(message)s'
)
logger = logging.getLogger(__name__)


class URLResolver:
    """
    Converts relative URLs into absolute, fully-qualified URLs.
    
    Responsibilities:
    - Detect if a URL is relative (e.g., '/login').
    - Prepend the Base URL to relative links.
    - Preserve absolute URLs (e.g., 'https://google.com').
    """

    def __init__(self, domain_url: str):
        """
        Args:
            domain_url (str): The context URL (usually the page's current URL).
        """
        self.domain_url = domain_url

    def resolve(self, urls: List[str]) -> List[str]:
        """
        Resolves a list of raw URLs against the base URL.
        
        Args:
            urls (List[str]): List of raw URLs (can be relative or absolute).
            
        Returns:
            List[str]: List of fully qualified absolute URLs.
        """
        if not urls:
            return []

        resolved_urls = []

        for url in urls:
            if not url:
                continue

            # urljoin is smart:
            # 1. If 'url' is absolute (starts with http/https), it returns 'url'.
            # 2. If 'url' is relative (starts with /, or ./), it joins with 'base_url'.
            # 3. If 'url' is protocol-relative (//cdn.com), it handles that too.
            
            try:
                absolute_url = urljoin(self.domain_url, url)
                resolved_urls.append(absolute_url)
            except ValueError as e:
                logger.warning(f"Failed to resolve URL '{url}': {e}")
                continue

        logger.debug(f"Resolved {len(resolved_urls)} URLs using base: {self.domain_url}")
        return resolved_urls
        


# --- Usage Example ---
if __name__ == "__main__":
    resolver = URLResolver("https://automationintesting.online/")
    urls = []
    resolved_urls = resolver.resolve(urls)
    import json
    print(json.dumps(resolved_urls, indent=2))