import logging
from enum import Enum
from urllib.parse import urlparse, parse_qsl, urlencode
from typing import Dict
import re

# =======================
# Enums
# =======================

class URLType(Enum):
    PAGE = "PAGE"
    ASSET = "ASSET"
    DATA = "DATA"
    API = "API"
    AUTH = "AUTH"
    UNKNOWN = "UNKNOWN"
    IGNORE = "IGNORE"


class Confidence(Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


# =======================
# Classifier
# =======================

class URLClassifier:

    # -------- Gate 1: Tracking Domains (DOMAIN ONLY) --------
    TRACKING_DOMAINS = {
        "doubleclick.net",
        "googletagmanager.com",
        "google-analytics.com",
        "analytics.google.com",
        "hotjar.com",
        "clarity.ms",
        "segment.com",
        "bat.bing.com",
        "snap.licdn.com",
        "stats.g.doubleclick.net",
    }

    # -------- Tracking Path Indicators (PATH ONLY) --------
    TRACKING_PATH_PATTERNS = (
        "/pixel",
        "/beacon",
        "/collect",
        "/analytics",
        "/tracking",
        "/ping",
        "/event",
    )

    # -------- Extensions --------
    ASSET_EXTS = (
        ".css", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp",
        ".woff", ".woff2", ".ttf", ".eot", ".otf",
        ".ico", ".mp4", ".webm", ".mp3", ".avi", ".mov",
        ".js",  # JS is asset but QA-relevant
    )

    DATA_EXTS = (
        ".json", ".xml", ".csv", ".rss", ".atom",
        ".zip", ".rar", ".tar", ".gz", ".sql",
    )

    # -------- API Patterns (Intent beats extension) --------
    API_PATTERNS = (
        "/api/",
        "/v1/", "/v2/", "/v3/", "/v4/",
        "/graphql",
        "/rpc",
        "/ajax/",
        "/admin-ajax.php",
        "/.well-known/",
    )

    # -------- Auth Keywords --------
    AUTH_KEYWORDS = (
        "login", "signin", "signup", "register",
        "logout", "reset", "password", "verify",
        "otp", "oauth", "callback", "sso", "forgot", "auth"
    )

    # -------- Query params to DROP in canonical --------
    TRACKING_QUERY_KEYS = (
        "utm_", "gclid", "fbclid", "yclid", "mc_cid", "mc_eid"
    )

    # =======================
    # Init
    # =======================

    def __init__(self, seed_domain: str):
        parsed = urlparse(seed_domain)
        self.seed_netloc = parsed.netloc.lower()
        self.seed_root = self._extract_root_domain(self.seed_netloc)

    # =======================
    # Public API
    # =======================

    def classify(self, url: str) -> Dict[str, str]:
        canonical_id = self._canonicalize(url)

        try:
            parsed = urlparse(url)
            scheme = parsed.scheme.lower()
            netloc = parsed.netloc.lower()
            path = parsed.path.lower()
            query = parsed.query.lower()

            # -------- Gate 0: Scheme --------
            if scheme not in ("http", "https"):
                return self._out(URLType.IGNORE, Confidence.HIGH, "Invalid scheme", canonical_id)

            # -------- Gate 1: Malformed --------
            if not netloc or "\\" in url or url.count("://") > 1:
                return self._out(URLType.IGNORE, Confidence.HIGH, "Malformed URL", canonical_id)

            is_internal = self._is_internal(netloc)

            # -------- Gate 2: Tracking (DOMAIN) --------
            if not is_internal and any(netloc.endswith(td) for td in self.TRACKING_DOMAINS):
                return self._out(URLType.IGNORE, Confidence.HIGH, "External tracking domain", canonical_id)

            # -------- Gate 3: Tracking (PATH) --------
            if any(tp in path for tp in self.TRACKING_PATH_PATTERNS):
                if not is_internal:
                    return self._out(URLType.IGNORE, Confidence.HIGH, "External tracking path", canonical_id)
                # Internal tracking paths are DATA/API-like
                return self._out(URLType.DATA, Confidence.LOW, "Internal analytics endpoint", canonical_id)

            # -------- Gate 4: API --------
            if any(pat in path for pat in self.API_PATTERNS):
                return self._out(
                    URLType.API,
                    Confidence.HIGH if is_internal else Confidence.LOW,
                    "API pattern detected",
                    canonical_id
                )

            # -------- Gate 5: Auth --------
            segments = path.split("/")
            if any(any(k in seg for k in self.AUTH_KEYWORDS) for seg in segments):
                return self._out(
                    URLType.AUTH,
                    Confidence.HIGH if is_internal else Confidence.LOW,
                    "Authentication endpoint",
                    canonical_id
                )

            # Query-based auth
            for key, _ in parse_qsl(query, keep_blank_values=True):
                if any(auth in key for auth in self.AUTH_KEYWORDS):
                    return self._out(
                        URLType.AUTH,
                        Confidence.HIGH if is_internal else Confidence.LOW,
                        "Authentication via query",
                        canonical_id
                    )

            # -------- Gate 6: Extensions --------
            if path.endswith(self.ASSET_EXTS):
                return self._out(
                    URLType.ASSET,
                    Confidence.HIGH if is_internal else Confidence.LOW,
                    "Static or executable asset",
                    canonical_id
                )

            if path.endswith(self.DATA_EXTS):
                return self._out(
                    URLType.DATA,
                    Confidence.HIGH if is_internal else Confidence.LOW,
                    "Data resource",
                    canonical_id
                )

            # -------- Gate 7: Default Page --------
            return self._out(
                URLType.PAGE,
                Confidence.HIGH if is_internal else Confidence.MEDIUM,
                "Navigable HTML page",
                canonical_id
            )

        except Exception as e:
            return self._out(URLType.IGNORE, Confidence.HIGH, f"Parse error: {e}", canonical_id)

    # =======================
    # Helpers
    # =======================

    def _out(self, t: URLType, c: Confidence, r: str, cid: str) -> Dict[str, str]:
        return {
            "type": t.value,
            "confidence": c.value,
            "reason": r,
            "canonical_id": cid,
        }

    def _canonicalize(self, url: str) -> str:
        """
        Canonical URL identity for deduplication.
        - Strip fragment
        - Remove tracking query params
        - Sort remaining params
        """
        parsed = urlparse(url)
        query_pairs = parse_qsl(parsed.query, keep_blank_values=True)

        clean_pairs = []
        for k, v in query_pairs:
            if any(k.startswith(tp) for tp in self.TRACKING_QUERY_KEYS):
                continue
            clean_pairs.append((k, v))

        clean_pairs.sort()
        clean_query = urlencode(clean_pairs, doseq=True)

        clean = parsed._replace(
            fragment="",
            query=clean_query,
            params=""
        )

        return clean.geturl()

    def _extract_root_domain(self, netloc: str) -> str:
        parts = netloc.split(".")
        if len(parts) < 2:
            return netloc

        common_cc = {"uk", "au", "nz", "in", "jp", "br", "cn", "ru", "za"}
        if parts[-1] in common_cc and len(parts) >= 3:
            return ".".join(parts[-3:])

        return ".".join(parts[-2:])

    def _is_internal(self, netloc: str) -> bool:
        return netloc == self.seed_netloc or netloc.endswith(f".{self.seed_root}")
