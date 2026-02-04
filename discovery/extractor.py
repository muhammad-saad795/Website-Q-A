import re
import json
import logging
from typing import List, Set, Optional, Union
from bs4 import BeautifulSoup, Tag, Comment

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class RawURLExtractor:
    """
    Production-grade raw URL extractor.
    
    Capabilities:
    1. Extracts raw URLs from HTML attributes (href, src, srcset, etc.).
    2. Extracts raw URLs from inline CSS and style tags.
    3. Extracts raw URLs from JavaScript strings.
    4. Extracts URLs from JSON-LD structured data.
    
    Constraint: DOES NOT normalize, resolve, or clean URLs.
    Returns the exact string found in the HTML.
    """

    # 1. Attributes that typically contain link entities
    # Includes standard HTML5 attributes and common metadata properties
    LINK_ATTRS = {
        'href', 'src', 'srcset', 'action', 'data', 'cite', 'poster', 
        'background', 'codebase', 'formaction', 'icon', 'manifest', 'ping',
        'longdesc', 'profile', 'usemap', 'archive', 'dynsrc', 'lowsrc',
        'classid', 'code' # For applets/objects
    }

    # 2. Meta tag properties that contain URLs
    META_LINK_PROPERTIES = {
        'og:image', 'og:image:url', 'og:image:secure_url', 'og:video', 
        'og:video:url', 'og:video:secure_url', 'og:url', 'twitter:image',
        'twitter:player', 'twitter:player:stream', 'canonical', 'alternate',
        'shortlink', 'amphtml', 'msapplication-TileImage', 'msapplication-config'
    }

    # 3. Patterns for Text/Script Extraction
    # Pattern for protocol-relative (//example.com) or absolute paths
    GENERIC_URL_PATTERN = re.compile(
        r'(?:https?|ftp|file)://[^\s<>"\'{}|\\^`\[\]]+|//(?:[^\s<>"\'{}|\\^`\[\]]+)'
    )
    
    # Pattern for CSS url()
    CSS_URL_PATTERN = re.compile(r'url\((["\']?)(.+?)\1\)')

    def extract(self, html: str) -> List[str]:
        """
        Extracts all raw link entities from the HTML.
        
        Args:
            html: Raw HTML string.
            
        Returns:
            A list of unique URL strings found in the document.
        """
        if not html:
            return []

        # Use 'lxml' for robust parsing, fallback to 'html.parser' if needed
        try:
            soup = BeautifulSoup(html, "lxml")
        except Exception:
            soup = BeautifulSoup(html, "html.parser")

        found_links = set()

        # 1. Scan DOM Attributes
        self._scan_attributes(soup, found_links)
        
        # 2. Scan CSS (Style tags and inline styles)
        self._scan_css(soup, found_links)
        
        # 3. Scan Scripts and JSON-LD
        self._scan_scripts(soup, found_links)
        
        # 4. Scan Comments
        self._scan_comments(soup, found_links)

        return sorted(list(found_links))

    # ========================================================================
    # SCANNERS
    # ========================================================================

    def _scan_attributes(self, soup: BeautifulSoup, url_set: Set[str]):
        """Iterate over all tags and extract raw values from specific attributes."""
        for tag in soup.find_all(True):
            if isinstance(tag, Comment):
                continue

            # Special handling for <meta> tags
            if tag.name == 'meta':
                self._extract_meta_urls(tag, url_set)
                continue

            attrs = tag.attrs
            if not attrs:
                continue

            for attr_name, attr_value in attrs.items():
                if not attr_value or not isinstance(attr_value, str):
                    continue

                # High Confidence Attributes
                if attr_name in self.LINK_ATTRS:
                    if attr_name == 'srcset':
                        self._extract_srcset(attr_value, url_set)
                    elif attr_name == 'ping':
                        # Ping attribute can contain space-separated URLs
                        for url in attr_value.split():
                            url_set.add(url)
                    else:
                        url_set.add(attr_value)
                
                # Fallback: Check if attribute name contains 'src' or 'href' (custom data attrs)
                elif 'src' in attr_name or 'href' in attr_name or 'url' in attr_name:
                    url_set.add(attr_value)

    def _extract_meta_urls(self, tag: Tag, url_set: Set[str]):
        """Extract content from meta tags if the property/name indicates a link."""
        property_val = tag.get('property') or tag.get('name') or tag.get('http-equiv')
        content_val = tag.get('content')

        if not content_val:
            return

        if property_val and property_val in self.META_LINK_PROPERTIES:
            url_set.add(content_val)
        else:
            # Generic check for link patterns in meta content
            if self.GENERIC_URL_PATTERN.search(content_val):
                url_set.add(content_val)

    def _scan_css(self, soup: BeautifulSoup, url_set: Set[str]):
        """Extract URLs from <style> blocks and style attributes."""
        # 1. Style Tags
        for style_tag in soup.find_all("style"):
            if style_tag.string:
                for match in self.CSS_URL_PATTERN.finditer(style_tag.string):
                    # match.group(2) is the content inside url()
                    url_set.add(match.group(2).strip())

        # 2. Inline Style Attributes
        for tag in soup.find_all(style=True):
            style_content = tag.get("style")
            if style_content:
                for match in self.CSS_URL_PATTERN.finditer(style_content):
                    url_set.add(match.group(2).strip())

    def _scan_scripts(self, soup: BeautifulSoup, url_set: Set[str]):
        """Extract URLs from JavaScript text and JSON-LD."""
        for script in soup.find_all("script"):
            script_type = script.get("type", "").lower()
            script_content = script.string
            if not script_content:
                continue

            # 1. JSON-LD
            if script_type == 'application/ld+json':
                try:
                    # Parse to find keys that look like URLs
                    self._extract_from_json(script_content, url_set)
                except json.JSONDecodeError:
                    pass
                continue

            # 2. Generic JS Strings
            # Look for quoted strings matching URL patterns
            # This matches "http://..." or 'http://...'
            for match in self.GENERIC_URL_PATTERN.finditer(script_content):
                url_set.add(match.group(0))

    def _scan_comments(self, soup: BeautifulSoup, url_set: Set[str]):
        """Extract URLs found inside HTML comments."""
        for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
            for match in self.GENERIC_URL_PATTERN.finditer(str(comment)):
                url_set.add(match.group(0))

    # ========================================================================
    # HELPERS
    # ========================================================================

    def _extract_srcset(self, content: str, url_set: Set[str]):
        """
        Parse srcset attribute.
        Format: 'image.jpg 1x, image2.jpg 2x'
        We only want the image part, not the descriptor.
        """
        parts = content.split(',')
        for part in parts:
            # Split by whitespace to separate URL from descriptor
            url_part = part.strip().split()[0]
            if url_part:
                url_set.add(url_part)

    def _extract_from_json(self, json_str: str, url_set: Set[str]):
        """
        Traverse JSON dictionary and collect values that look like URLs.
        """
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            return

        if isinstance(data, dict):
            for value in data.values():
                self._process_json_value(value, url_set)
        elif isinstance(data, list):
            for item in data:
                self._process_json_value(item, url_set)

    def _process_json_value(self, value: any, url_set: Set[str]):
        if isinstance(value, str):
            # Simple heuristic: if it looks like a link, take it
            if self.GENERIC_URL_PATTERN.match(value):
                url_set.add(value)
        elif isinstance(value, dict):
            for v in value.values():
                self._process_json_value(v, url_set)
        elif isinstance(value, list):
            for item in value:
                self._process_json_value(item, url_set)

# ========================================================================
# USAGE EXAMPLE
# ========================================================================

if __name__ == "__main__":
    html_doc = """
    <html>
    <head>
        <link rel="canonical" href="https://example.com/canonical">
        <style>
            body { background: url("/bg.png"); }
            .box { background: url(http://site.com/img.jpg); }
        </style>
        <script>
            var link1 = "http://dynamic.com/script.js";
            var link2 = '//cdn.com/lib.js';
        </script>
        <script type="application/ld+json">
        {
            "@context": "http://schema.org",
            "url": "http://example.com/structured"
        }
        </script>
    </head>
    <body>
        <a href="/relative/path">Link</a>
        <img src="/images/img.png" srcset="img-1x.png 1x, img-2x.png 2x">
        <div data-custom-src="lazy.html"></div>
        <!-- Raw link: http://commented.com -->
    </body>
    </html>
    """

    extractor = RawURLExtractor()
    urls = extractor.extract(html_doc)

    print(f"Found {len(urls)} raw entities:")
    for u in urls:
        print(u)