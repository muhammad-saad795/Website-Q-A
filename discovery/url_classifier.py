import re
import logging
from enum import Enum
from urllib.parse import urlparse, parse_qs
from typing import List, Dict, Set, Tuple

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class URLCategory(Enum):
    """
    Refined categories.
    
    - PAGE: Navigable HTML.
    - API_ENDPOINT: Service definitions.
    - STATIC_ASSET: Media/Code files.
    - DOCUMENTATION: Help/API docs.
    - EXTERNAL: Valid outbound links.
    - INVALID: Garbage, attribute leaks, or non-navigable schemas.
    """
    PAGE = "PAGE"
    API_ENDPOINT = "API_ENDPOINT"
    STATIC_ASSET = "STATIC_ASSET"
    DOCUMENTATION = "DOCUMENTATION"
    EXTERNAL = "EXTERNAL"
    INVALID = "INVALID"


class URLClassifier:
    """
    Robust URL Classifier with Garbage & Schema Detection.
    """

    # ========================
    # 1. Heuristic Constants
    # ========================

    # Extensions
    ASSET_EXTENSIONS = {
        '.css', '.js', '.map', '.woff', '.woff2', '.ttf', '.eot', '.otf',
        '.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.ico', '.bmp',
        '.mp4', '.webm', '.mp3', '.wav', '.ogg', '.avi', '.mov',
        '.zip', '.tar', '.gz', '.rar', '.7z', '.pfx', '.crt', '.pem',
        '.json', '.xml', '.csv', '.xlsx', '.xls', '.ppt', '.pptx', '.bin', '.exe',
        '.jfif','.torrent'
    }

    DOC_EXTENSIONS = {'.pdf', '.txt', '.rtf', '.doc', '.docx'}

    API_FORMAT_PARAMS = {
        'wsdl', 'wadl', 'wadl2', 'swagger', 'openapi', 
        'format=json', 'format=xml', 'callback', 'jsonp'
    }

    API_PATH_KEYWORDS = {
        '/api/', '/rest/', '/graphql', '/soap/', '/rpc/',
        '/services/', '/endpoint/', '/hook/', '/webhook/'
    }

    DOC_PATH_KEYWORDS = {
        '/docs/', '/help/', '/guide/', '/faq/', '/support/',
        '/tutorial/', '/manual/', '/readme', '/changelog',
        '/swagger', '/api-docs', '/redoc', '/postman'
    }

    # Domains that are schemas/technical references (Not real links to click)
    SCHEMA_DOMAINS = {
        'www.w3.org', 'schema.org', 'json-ld.org', 
        'iana.org', 'example.com', 'test.com', 'localhost'
    }

    # Keywords found in leaked HTML attributes that became URLs
    GARBAGE_ATTRIBUTES = {
        'nofollow', 'noindex', 'notranslate', 'noarchive', 
        'nosnippet', 'noreferrer', 'noopener'
    }

    def __init__(self, target_domain: str):
        """
        Initialize classifier.
        
        Args:
            target_domain: Can be either a domain (e.g., "example.com") or a full URL (e.g., "https://example.com")
        """
        # Handle both domain and full URL inputs
        if target_domain.startswith(('http://', 'https://')):
            from urllib.parse import urlparse
            parsed = urlparse(target_domain)
            self.target_domain = parsed.netloc.lower()
        else:
            self.target_domain = target_domain.lower()
            
        self.target_root = self._extract_root(self.target_domain)

    def classify(self, url: str) -> Dict[str, str]:
        if not url or not isinstance(url, str):
            return self._result(URLCategory.INVALID, "Empty or non-string")

        # 1. Pre-Clean Syntax
        # Handle trailing backslashes (JS escaping issue) and dots
        url = url.rstrip('\\').rstrip('.')

        # 2. Parse
        try:
            parsed = urlparse(url)
        except ValueError:
            return self._result(URLCategory.INVALID, "Unparseable URL")

        # 3. Scheme Check
        if parsed.scheme not in ('http', 'https'):
            return self._result(URLCategory.INVALID, "Non-HTTP scheme")

        # 4. Garbage Detection (New Layer - Handles your specific cases)
        if self._is_garbage_or_leak(url, parsed):
            return self._result(URLCategory.INVALID, "Garbage/Meta attribute leak")

        # 5. Schema Technical Check (W3C, etc.)
        if parsed.netloc in self.SCHEMA_DOMAINS:
            # Even if it matches extension, treat as invalid for crawling purposes
            # because it's a reference, not a page
            return self._result(URLCategory.INVALID, "Technical/Schema reference")

        # 6. External Check
        netloc_no_port = parsed.netloc.split(':')[0].lower()
        if not self._is_internal(netloc_no_port):
            return self._result(URLCategory.EXTERNAL, "Outbound link")

        # 7. Clean Path (Remove Matrix Params like ;jsessionid)
        clean_path = re.split(r'[;?]', parsed.path)[0].lower()

        # 8. Classification Waterfall
        
        # A. STATIC ASSETS
        if clean_path.endswith(tuple(self.ASSET_EXTENSIONS)):
            return self._result(URLCategory.STATIC_ASSET, "Static file extension")

        # B. API ENDPOINTS
        query_lower = parsed.query.lower()
        param_match = any(qp in query_lower for qp in self.API_FORMAT_PARAMS)
        path_match = any(api in clean_path for api in self.API_PATH_KEYWORDS)
        
        if param_match or path_match:
            return self._result(URLCategory.API_ENDPOINT, "Machine-readable endpoint")

        # C. DOCUMENTATION
        if clean_path.endswith(tuple(self.DOC_EXTENSIONS)):
            return self._result(URLCategory.DOCUMENTATION, "Document file")
        if any(doc in clean_path for doc in self.DOC_PATH_KEYWORDS):
            return self._result(URLCategory.DOCUMENTATION, "Help/Documentation path")

        # D. PAGE (The Default)
        return self._result(URLCategory.PAGE, "Navigable HTML Interface")

    def categorize_list(self, url_list: List[str]) -> Dict[str, Dict]:
        return {u: self.classify(u) for u in url_list}

    # ========================
    # 3. Helper Methods
    # ========================

    def _is_garbage_or_leak(self, url: str, parsed: urlparse) -> bool:
        """
        Detects false-positives caused by HTML Attribute Leaks.
        """
        path = parsed.path

        # Case 1: Spaces in path
        # "A platform for testing..."
        if ' ' in path:
            return True

        # Case 2: Viewport leaks
        # "width=device-width, initial-scale=1"
        if 'width=device-width' in path or 'initial-scale=' in path:
            return True

        # Case 3: Attribute Values
        # "/notranslate", "/nofollow"
        # Check if path is exactly one of the known garbage attributes
        if path in self.GARBAGE_ATTRIBUTES:
            return True
            
        # Case 4: Random sentence-like structures
        # If path has no extension and looks like a sentence
        if '.' not in path and len(path) > 20 and ' ' not in path:
            # Heuristic: If it contains common stopwords like "for", "the", "is"
            # and has no extension.
            # e.g. /Aplatformfortestingrestfulwebservices (no spaces, extracted from meta)
            text = path.lower().replace('-', ' ').replace('_', ' ')
            if any(stop in text for stop in [' for ', ' a ', ' the ', ' is ']):
                return True

        return False

    def _is_internal(self, netloc: str) -> bool:
        if not netloc:
            return False
        if netloc == self.target_domain:
            return True
        if netloc.endswith('.' + self.target_root):
            return True
        return False

    def _extract_root(self, domain: str) -> str:
        parts = domain.split('.')
        if len(parts) < 2:
            return domain
        known_tlds = {'co.uk', 'com.au', 'org.uk', 'net.nz', 'gov.uk'}
        if len(parts) > 2:
            potential_root = ".".join(parts[-2:])
            if potential_root in known_tlds:
                return ".".join(parts[-3:])
        return ".".join(parts[-2:])

    def _result(self, category: URLCategory, reason: str) -> Dict[str, str]:
        return {
            "category": category.value,
            "reason": reason
        }


# ==========================================
# Verification (AutomationInTesting Example)
# ==========================================
if __name__ == "__main__":
    raw_urls =[]

    classifier = URLClassifier(target_domain="https://automationintesting.online")
    results = classifier.categorize_list(raw_urls)
    import json
    print(json.dumps(results, indent=4))