import logging
from typing import List, Dict, Any, Union
from urllib.parse import urljoin, urlparse, urlunparse

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class URLNormalizer:
    """
    Converts raw extracted URLs into syntactically testable, absolute candidates.
    
    Responsibilities:
    1. Resolves relative paths and protocol-relative links against the base URL.
    2. Retains fragment information attached to the full page URL.
    3. Filters out non-HTTP schemes (javascript:, mailto:) and malformed syntax.
    """

    # Schemes that are considered "junk" for web scraping/testing purposes
    JUNK_SCHEMES = {
        "javascript", "mailto", "tel", "sms", "data", "file", "blob", "about", "ed2k", "magnet"
    }

    def process(self, raw_urls: List[Union[str, bytes]], final_url: str) -> List[Dict[str, Any]]:
        """
        Normalizes a list of raw URLs based on the context of the final loaded URL.

        Args:
            raw_urls: List of raw strings (or bytes) extracted from HTML/JS.
            final_url: The absolute URL of the page (from loader), used as the base context.

        Returns:
            A list of dictionaries containing the original, normalized, and parsed components.
        """
        normalized_results = []

        # Clean the base URL to ensure joining works correctly
        base_url = final_url.strip()

        for raw_item in raw_urls:
            # 1. Decode bytes if necessary
            if isinstance(raw_item, bytes):
                try:
                    raw_item = raw_item.decode('utf-8')
                except UnicodeDecodeError:
                    # Cannot decode, skip this URL
                    continue

            # 2. Basic String Cleaning (Whitespace)
            # We keep the 'original' version slightly clean for readability, 
            # but process the stripped version.
            original_clean = raw_item.strip()
            
            if not original_clean:
                continue

            # 3. Junk Filter: Schemes
            # Check for obvious junk schemes before expensive parsing
            lower_raw = original_clean.lower()
            if any(lower_raw.startswith(scheme + ":") for scheme in self.JUNK_SCHEMES):
                continue

            # 4. Resolution
            # - //example.com -> Inherits scheme from base_url
            # - /path -> Attaches base origin
            # - #fragment -> Attaches to current base_url path
            try:
                candidate_url = urljoin(base_url, original_clean)
            except ValueError:
                # urljoin can raise ValueError on malformed IPv6 or extremely long URLs
                continue

            # 5. Parse and Validate Structure
            parsed = urlparse(candidate_url)

            # Rule: "http:// (no host)" -> Remove malformed syntax
            # If the scheme requires a host (http, https) but netloc is empty, it's junk.
            if parsed.scheme in ('http', 'https', 'ftp') and not parsed.netloc:
                continue

            # 6. Component Normalization
            # Convert scheme and host to lowercase for consistency
            norm_scheme = parsed.scheme.lower()
            norm_host = parsed.netloc.lower()
            
            # Reconstruct the normalized URL to ensure consistency
            # (e.g., ensuring scheme/host are lowercased)
            normalized_url = urlunparse((
                norm_scheme,
                norm_host,
                parsed.path,
                parsed.params, # Parameters (rarely used in HTTP path)
                parsed.query,
                parsed.fragment
            ))

            # 7. Construct Output Object
            result_obj = {
                "original": original_clean,
                "normalized": normalized_url,
                "components": {
                    "scheme": norm_scheme,
                    "host": norm_host,
                    "path": parsed.path,
                    "query": parsed.query,
                    "fragment": parsed.fragment
                }
            }

            normalized_results.append(result_obj)

        return normalized_results




if __name__ == "__main__":
    url = [
        "//stats.wp.com",
        "/wp-content/uploads/*",
        "https://practicetestautomation.com/wp-json/",
        "https://practicetestautomation.com/#breadcrumb",
        "https://practicetestautomation.com/#primaryimage",
        "https://i0.wp.com/practicetestautomation.com/wp-content/uploads/2019/10/cropped-5.png?fit=32%2C32&ssl=1",
        "//fonts.googleapis.com",
        "/wp-admin/*",
        "https://practicetestautomation.com/contact/",
        "http://",
        "https://practicetestautomation.com/wp-admin/admin-post.php?action=mailpoet_subscription_form",
        "https://practicetestautomation.com/wp-includes/js/jquery/jquery.min.js?ver=3.7.1",
        "https://practicetestautomation.com/xmlrpc.php?rsd",
        "https://practicetestautomation.com/wp-content/themes/modern-store-modified/js/build/production.min.js?ver=6.9",
        "https://practicetestautomation.com/",
        "https://practicetestautomation.com/courses/",
        "https://i0.wp.com/practicetestautomation.com/wp-content/uploads/2019/10/Logo-1.png?w=305&ssl=1",
        "https://i0.wp.com/practicetestautomation.com/wp-content/uploads/2019/10/Logo-1.png?resize=300%2C94&ssl=1",
        "https://practicetestautomation.com/wp-content/themes/modern-store-modified/assets/font-awesome/css/all.min.css?ver=6.9",
        "https://practicetestautomation.com/wp-content/plugins/mailpoet/assets/dist/css/mailpoet-public.b1f0906e.css?ver=6.9",
        "https://www.udemy.com/course/xpath-locators-for-selenium/?referralCode=ACB28329B5AC2333DDCC",
        "https://i0.wp.com/practicetestautomation.com/wp-content/uploads/2019/10/cropped-5.png?fit=192%2C192&ssl=1",
        "https://practicetestautomation.com/comments/feed/",
        "//secure.gravatar.com",
        "//i0.wp.com",
        "https://practicetestautomation.com/wp-admin/admin-ajax.php",
        "/wp-content/themes/modern-store-modified/*",
        "https://fonts.googleapis.com/css?family=Ropa+Sans%3A400%2C400i%2C700%2C700i%7CRubik%3A400%2C400i%2C700%2C700i%7CShadows+Into+Light%3A400%2C400i%2C700%2C700i%7CSpace+Mono%3A400%2C400i%2C700%2C700i%7CSpectral%3A400%2C400i%2C700%2C700i%7CSue+Ellen+Francisco%3A400%2C400i%2C700%2C700i%7CTitillium+Web%3A400%2C400i%2C700%2C700i%7CUbuntu%3A400%2C400i%2C700%2C700i%7CVarela%3A400%2C400i%2C700%2C700i%7CVollkorn%3A400%2C400i%2C700%2C700i%7CWork+Sans%3A400%2C400i%2C700%2C700i%7CYatra+One%3A400%2C400i%2C700%2C700i&ver=6.9",
        "https://practicetestautomation.com/?s={search_term_string}",
        "https://s.w.org/images/core/emoji/17.0.2/svg/",
        "https://pixel.wp.com/g.gif?v=ext&blog=167878209&post=23&tz=-5&srv=practicetestautomation.com&j=1%3A14.5&host=practicetestautomation.com&ref=&fcp=18724&rand=0.919237049961694",
        "https://practicetestautomation.com/wp-content/plugins/mailpoet/assets/dist/js/public.js?ver=5.10.0",
        "https://www.udemy.com/course/selenium-for-beginners/?referralCode=A21BE51035C15406EFA4",
        "https://i0.wp.com/practicetestautomation.com/wp-content/uploads/2019/10/round-avatar.png?resize=480%2C478&ssl=1",
        "https://i0.wp.com/practicetestautomation.com/wp-content/uploads/2019/10/cropped-5.png?fit=270%2C270&ssl=1",
        "https://practicetestautomation.com/feed/",
        "https://practicetestautomation.com/wp-includes/js/jquery/jquery-migrate.min.js?ver=3.4.1",
        "https://s.w.org/images/core/emoji/17.0.2/72x72/",
        "//v0.wordpress.com",
        "https://practicetestautomation.com/#website",
        "https://i0.wp.com/practicetestautomation.com/wp-content/uploads/2019/10/round-avatar.png?resize=300%2C300&ssl=1",
        "https://i0.wp.com/practicetestautomation.com/wp-content/uploads/2019/10/Logo-1.png?fit=305%2C96&ssl=1",
        "https://practicetestautomation.com/wp-includes/js/wp-emoji-release.min.js?ver=6.9",
        "https://practicetestautomation.com/wp-json/oembed/1.0/embed?url=https%3A%2F%2Fpracticetestautomation.com%2F",
        "https://practicetestautomation.com/wp-content/themes/modern-store-modified/style.css?ver=6.9",
        "https://schema.org",
        "https://i0.wp.com/practicetestautomation.com/wp-content/uploads/2019/10/round-avatar.png?fit=480%2C478&ssl=1",
        "https://i0.wp.com/practicetestautomation.com/wp-content/uploads/2019/10/round-avatar.png?resize=150%2C150&ssl=1",
        "/*",
        "/wp-*.php",
        "https://fonts.googleapis.com/css?family=Heebo%3A400%2C400i%2C700%2C700i%7CIBM+Plex%3A400%2C400i%2C700%2C700i%7CInconsolata%3A400%2C400i%2C700%2C700i%7CIndie+Flower%3A400%2C400i%2C700%2C700i%7CInknut+Antiqua%3A400%2C400i%2C700%2C700i%7CInter%3A400%2C400i%2C700%2C700i%7CKarla%3A400%2C400i%2C700%2C700i%7CLibre+Baskerville%3A400%2C400i%2C700%2C700i%7CLibre+Franklin%3A400%2C400i%2C700%2C700i%7CMontserrat%3A400%2C400i%2C700%2C700i%7CNeuton%3A400%2C400i%2C700%2C700i%7CNotable%3A400%2C400i%2C700%2C700i%7CNothing+You+Could+Do%3A400%2C400i%2C700%2C700i%7CNoto+Sans%3A400%2C400i%2C700%2C700i%7CNunito%3A400%2C400i%2C700%2C700i%7COld+Standard+TT%3A400%2C400i%2C700%2C700i%7COxygen%3A400%2C400i%2C700%2C700i%7CPacifico%3A400%2C400i%2C700%2C700i%7CPoppins%3A400%2C400i%2C700%2C700i%7CProza+Libre%3A400%2C400i%2C700%2C700i%7CPT+Sans%3A400%2C400i%2C700%2C700i%7CPT+Serif%3A400%2C400i%2C700%2C700i%7CRakkas%3A400%2C400i%2C700%2C700i%7CReenie+Beanie%3A400%2C400i%2C700%2C700i%7CRoboto+Slab%3A400%2C400i%2C700%2C700i&ver=6.9",
        "https://practicetestautomation.com/wp-content/uploads/2019/10/round-avatar.png",
        "https://practicetestautomation.com/blog/",
        "https://fonts.googleapis.com/css?family=Abril+FatFace%3A400%2C400i%2C700%2C700i%7CAlegreya%3A400%2C400i%2C700%2C700i%7CAlegreya+Sans%3A400%2C400i%2C700%2C700i%7CAmatic+SC%3A400%2C400i%2C700%2C700i%7CAnonymous+Pro%3A400%2C400i%2C700%2C700i%7CArchitects+Daughter%3A400%2C400i%2C700%2C700i%7CArchivo%3A400%2C400i%2C700%2C700i%7CArchivo+Narrow%3A400%2C400i%2C700%2C700i%7CAsap%3A400%2C400i%2C700%2C700i%7CBarlow%3A400%2C400i%2C700%2C700i%7CBioRhyme%3A400%2C400i%2C700%2C700i%7CBonbon%3A400%2C400i%2C700%2C700i%7CCabin%3A400%2C400i%2C700%2C700i%7CCairo%3A400%2C400i%2C700%2C700i%7CCardo%3A400%2C400i%2C700%2C700i%7CChivo%3A400%2C400i%2C700%2C700i%7CConcert+One%3A400%2C400i%2C700%2C700i%7CCormorant%3A400%2C400i%2C700%2C700i%7CCrimson+Text%3A400%2C400i%2C700%2C700i%7CEczar%3A400%2C400i%2C700%2C700i%7CExo+2%3A400%2C400i%2C700%2C700i%7CFira+Sans%3A400%2C400i%2C700%2C700i%7CFjalla+One%3A400%2C400i%2C700%2C700i%7CFrank+Ruhl+Libre%3A400%2C400i%2C700%2C700i%7CGreat+Vibes%3A400%2C400i%2C700%2C700i&ver=6.9",
        "https://stats.wp.com/e-202604.js",
        "https://i0.wp.com/practicetestautomation.com/wp-content/uploads/2019/10/round-avatar.png?w=480&ssl=1",
        "https://practicetestautomation.com/privacy-policy/",
        "https://practicetestautomation.com/#/schema/person/b8f6670c2b21daaf53aa48dbc7f148b1",
        "https://wp.me/PbmoN3-n",
        "/*\\\\?(.+)",
        "https://practicetestautomation.com/practice/",
        "https://practicetestautomation.com/wp-json/oembed/1.0/embed?url=https%3A%2F%2Fpracticetestautomation.com%2F&format=xml",
        "https://practicetestautomation.com/wp-json/wp/v2/pages/23",
        "https://i0.wp.com/practicetestautomation.com/wp-content/uploads/2019/10/cropped-5.png?fit=180%2C180&ssl=1",
        "/wp-content/*",
        "/wp-content/plugins/*",
        "https://practicetestautomation.com/wp-content/plugins/bluehost-wordpress-plugin/vendor/newfold-labs/wp-module-performance/build/assets/link-prefetch.min.js?ver=4.7.2",
        "//fonts.googleapis.com/css?family=Lato%3A400%2C400i%2C900&ver=6.9",
        "https://practicetestautomation.com/#/schema/person/image/"
    ]
    url_normalizer = URLNormalizer()
    results = url_normalizer.process(url, "https://practicetestautomation.com/")
    import json
    print(json.dumps(results, indent=4))