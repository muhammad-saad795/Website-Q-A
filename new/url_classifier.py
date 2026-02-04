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
    raw_urls =[
    "http://www.w3.org/1999/xhtml",
    "http://www.w3.org/2000/svg",
    "https://cdn.jsdelivr.net/npm/bootstrap@5.2.0/dist/js/bootstrap.bundle.min.js",
    "https://code.jquery.com/jquery-3.6.2.js",
    "https://code.jquery.com/ui/1.13.2/jquery-ui.js",
    "https://use.fontawesome.com/releases/v5.8.1/css/all.css",
    "https://use.fontawesome.com/releases/v5.8.1/css/v4-shims.css",
    "https://www.google-analytics.com/g/collect?v=2&tid=G-WNRX3M9ZS8&gtm=45je61r1v898544080za200zd898544080&_p=1769769303805&gcd=13l3l3l3l1l1&npa=0&dma=0&cid=1809280449.1769769305&ul=en-us&sr=1280x720&uaa=x86&uab=64&uafvl=Chromium%3B143.0.7499.4%7CNot%2520A(Brand%3B24.0.0.0&uamb=0&uam=&uap=Linux&uapv=6.14.0&uaw=0&are=1&frm=0&pscdl=noapi&_s=1&tag_exp=103116026~103200004~104527906~104528501~104684208~104684211~115938465~115938469~116185181~116185182~116988315~117041587&sid=1769769304&sct=1&seg=0&dl=https%3A%2F%2Fwww.qa-practice.com%2Felements%2Finput%2Fsimple&dt=Input%20Field%20%7C%20Text%20Input%20%7C%20QA%20Practice&en=page_view&_fv=1&_nsi=1&_ss=1&_c=1&_ee=1&tfd=1671",
    "https://www.googletagmanager.com/gtag/js?id=G-WNRX3M9ZS8",
    "https://www.qa-practice.com/",
    "https://www.qa-practice.com/contact/",
    "https://www.qa-practice.com/elements/alert",
    "https://www.qa-practice.com/elements/button",
    "https://www.qa-practice.com/elements/checkbox",
    "https://www.qa-practice.com/elements/dragndrop",
    "https://www.qa-practice.com/elements/iframe/iframe_page",
    "https://www.qa-practice.com/elements/input",
    "https://www.qa-practice.com/elements/input/01/30/2026%2015:35:03",
    "https://www.qa-practice.com/elements/input/5.0%20(X11;%20Linux%20x86_64)%20AppleWebKit/537.36%20(KHTML,%20like%20Gecko)%20Chrome/143.0.0.0%20Safari/537.36",
    "https://www.qa-practice.com/elements/input/Mozilla/5.0%20(X11;%20Linux%20x86_64)%20AppleWebKit/537.36%20(KHTML,%20like%20Gecko)%20Chrome/143.0.0.0%20Safari/537.36",
    "https://www.qa-practice.com/elements/input/application/pdf",
    "https://www.qa-practice.com/elements/input/application/x-www-form-urlencoded",
    "https://www.qa-practice.com/elements/input/email",
    "https://www.qa-practice.com/elements/input/index.html",
    "https://www.qa-practice.com/elements/input/index_v2.html",
    "https://www.qa-practice.com/elements/input/passwd",
    "https://www.qa-practice.com/elements/input/simple",
    "https://www.qa-practice.com/elements/input/simple#req_text",
    "https://www.qa-practice.com/elements/input/text/css",
    "https://www.qa-practice.com/elements/input/text/html",
    "https://www.qa-practice.com/elements/input/text/pdf",
    "https://www.qa-practice.com/elements/new_tab",
    "https://www.qa-practice.com/elements/popup",
    "https://www.qa-practice.com/elements/select",
    "https://www.qa-practice.com/elements/textarea",
    "https://www.qa-practice.com/favicon.ico",
    "https://www.qa-practice.com/static/home/css/header.css",
    "https://www.qa-practice.com/static/home/js/header.js",
    "https://www.qa-practice.com/static/home/js/main.js",
    "https://www.qa-practice.com/static/home/logo.png",
    "https://www.qa-practice.com/static/home/styles/main.css",
    "https://www.qa-practice.com/whats_new/",
    "javascript:;"
]
    classifier = URLClassifier(target_domain="https://qa-practice.com")
    results = classifier.categorize_list(raw_urls)
    import json
    print(json.dumps(results, indent=4))