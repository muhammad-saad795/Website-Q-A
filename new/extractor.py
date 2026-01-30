import urllib.parse
import re

def clean_and_filter_urls(urls, base_url=None):
    """
    Filters a list of URLs, returning only valid HTTP/HTTPS links.
    Handles relative URLs, decoding, and skips non-URL schemes.
    
    :param urls: list of URL strings (possibly messy)
    :param base_url: optional, used to resolve relative URLs
    :return: sorted list of cleaned, absolute URLs
    """
    real_links = set()
    
    for url in urls:
        if not url or not isinstance(url, str):
            continue
        
        # Remove leading/trailing whitespace & HTML entities
        url = url.strip()
        url = urllib.parse.unquote(url)          # decode URL-encoded characters
        url = re.sub(r'[\r\n\t]+', '', url)     # remove newlines/tabs
        url = url.replace('&amp;', '&')          # decode HTML entities

        # Skip obviously invalid or unsafe URLs
        if not url or '<' in url or '>' in url:
            continue
        if url.lower().startswith(('javascript:', 'data:', 'mailto:', 'tel:')):
            continue

        # Resolve relative URLs if base_url is provided
        try:
            full_url = urllib.parse.urljoin(base_url or '', url)
            parsed = urllib.parse.urlparse(full_url)
            if parsed.scheme not in ('http', 'https'):
                continue
            # Normalize: remove fragments, strip trailing slashes
            clean_url = urllib.parse.urlunparse(parsed._replace(fragment='')).rstrip('/')
            real_links.add(clean_url)
        except Exception:
            continue

    return sorted(real_links)
