import re
import logging
import json
from typing import List, Dict, Any, Set, Tuple
from bs4 import BeautifulSoup, Tag, Comment

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class Extractor:
    """
    Universal, QA-grade URL extractor.
    Features:
    1. Exhaustive URL Extraction from tags, attributes, CSS, and scripts.
    """

    # 1. URL Patterns
    URL_PATTERN = re.compile(
        r'\b(?:https?|ftp|file|blob|mailto|tel):(?:\/\/)?[^\s<>"\'{}|\\^`\[\]]+', 
        re.IGNORECASE
    )
    PROTOCOL_RELATIVE = re.compile(r'\/\/[^\s<>"\'{}|\\^`\[\]]+')

    # 2. Content-Specific Patterns
    CSS_URL_PATTERN = re.compile(r'url\(["\']?(.*?)["\']?\)')
    LIST_SEPARATOR = re.compile(r'[\s,]+')

    # 3. Attribute Hints
    HIGH_CONFIDENCE_ATTRS = {
        'href', 'src', 'srcset', 'action', 'data', 'content', 'poster', 
        'cite', 'background', 'codebase', 'classid', 'usemap', 'longdesc',
        'profile', 'formaction', 'icon', 'manifest', 'ping'
    }
    
    DATA_ATTR_PREFIXES = ('data-', 'ng-', 'v-', 'xlink:', 'on')


    def extract(self, html: str) -> Dict[str, List[str]]:
        """
        Extracts all unique URLs found in the provided HTML.
        Returns a dictionary with 'urls' key.
        """
        if not html:
            return {"urls": []}

        soup = BeautifulSoup(html, "lxml")
        
        found_urls = set()
        self._scan_all_tags(soup, found_urls)
        self._scan_embedded_css(soup, found_urls)
        self._scan_scripts_and_jsonld(soup, found_urls)

        return {
            "urls": list(found_urls)
        }

    # ========================================================================
    # 1. DOM EXHAUSTION
    # ========================================================================

    def _scan_all_tags(self, soup: BeautifulSoup, url_set: Set[str]):
        for tag in soup.find_all(True):
            if isinstance(tag, Comment):
                continue
            attrs = tag.attrs
            if not attrs:
                continue

            for attr_name, attr_value in attrs.items():
                if not attr_value or not isinstance(attr_value, str):
                    continue

                if attr_name == 'srcset':
                    self._extract_srcset(attr_value, url_set)
                    continue

                if attr_name == 'ping':
                    for part in self.LIST_SEPARATOR.split(attr_value):
                        url_set.add(self._clean_url(part.strip()))
                    continue

                if attr_name in self.HIGH_CONFIDENCE_ATTRS:
                    url_set.add(self._clean_url(attr_value.strip()))
                    continue

                is_data_attr = attr_name.startswith(self.DATA_ATTR_PREFIXES)
                contains_protocol = '://' in attr_value or attr_value.startswith('//')
                
                if is_data_attr or contains_protocol:
                    self._scan_string_for_urls(attr_value, url_set)

    def _clean_url(self, url: str) -> str:
        """Normalizes URL strings."""
        if not url:
            return url
        clean = url.strip()
        clean = clean.rstrip('\\').rstrip('/')
        return clean

    def _extract_srcset(self, content: str, url_set: Set[str]):
        candidates = content.split(',')
        for cand in candidates:
            url_part = cand.strip().split()[0]
            if url_part:
                url_set.add(self._clean_url(url_part))

    def _scan_string_for_urls(self, text: str, url_set: Set[str]):
        matches = self.URL_PATTERN.findall(text)
        for m in matches:
            url_set.add(self._clean_url(m))
        if not matches:
            matches = self.PROTOCOL_RELATIVE.findall(text)
            for m in matches:
                url_set.add(self._clean_url(m))

    # ========================================================================
    # 2. EMBEDDED CSS
    # ========================================================================

    def _scan_embedded_css(self, soup: BeautifulSoup, url_set: Set[str]):
        for style_tag in soup.find_all("style"):
            if style_tag.string:
                self._extract_from_css_text(style_tag.string, url_set)

        for tag in soup.find_all(style=True):
            css_content = tag.get("style")
            if css_content:
                self._extract_from_css_text(css_content, url_set)

    def _extract_from_css_text(self, css_text: str, url_set: Set[str]):
        matches = self.CSS_URL_PATTERN.findall(css_text)
        for m in matches:
            clean = self._clean_url(m.strip('\'"'))
            if clean:
                url_set.add(clean)

    # ========================================================================
    # 3. SCRIPTS & JSON-LD
    # ========================================================================

    def _scan_scripts_and_jsonld(self, soup: BeautifulSoup, url_set: Set[str]):
        for script in soup.find_all("script"):
            script_type = script.get("type", "").lower()
            script_content = script.string
            if not script_content:
                continue

            if script_type == 'application/ld+json':
                try:
                    data = json.loads(script_content)
                    self._extract_urls_from_dict(data, url_set)
                except json.JSONDecodeError:
                    pass

            js_matches = re.findall(r'["\']((https?:|/)[^"\']+)["\']', script_content)
            for m in js_matches:
                url_set.add(self._clean_url(m[0]))

    def _extract_urls_from_dict(self, data: Any, url_set: Set[str]):
        if isinstance(data, str):
            if self.URL_PATTERN.match(data) or self.PROTOCOL_RELATIVE.match(data):
                url_set.add(self._clean_url(data))
        elif isinstance(data, dict):
            for v in data.values():
                self._extract_urls_from_dict(v, url_set)
        elif isinstance(data, list):
            for item in data:
                self._extract_urls_from_dict(item, url_set)
