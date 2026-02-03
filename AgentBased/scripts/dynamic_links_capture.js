/**
 * normalized_url_extractor.js
 *
 * Runs in page context. Returns an array of normalized URLs (strings) and nothing else.
 * - Exhaustive but safe: attributes, srcset, CSS url(), JSON-LD, scripts, performance,
 *   inline handlers, history.state, location, minimal runtime object scan (configurable).
 * - Normalization: resolves relative/protocol-relative URLs, lowercases host, removes fragments,
 *   collapses duplicate slashes, strips default ports, trims trailing slashes (except root).
 * - Strong rejects for junk schemes, patterns, overly-long or clearly-serialized strings.
 *
 * Usage (paste in DevTools or run via page.evaluate):
 *   const urls = await (async () => { ... paste script ... })();
 *   // urls is an array of normalized URL strings
 */

(async function normalizedUrlExtractor() {
    'use strict';

    const cfg = {
        stripFragment: true,
        followProtocolRelative: true,
        maxUrlLength: 2048,
        maxRuntimeDepth: 2,
        maxRuntimeObjects: 300, // conservative to avoid freezing pages
        runtimeStringMinSlashCount: 1
    };

    // storage for normalized results
    const normalizedSet = new Set();
    const rawOnlySet = new Set(); // in case normalization fails we ignore per user request

    // quick helpers / regex
    const JUNK_SCHEME_RE = /^(javascript|data|mailto|tel|blob|file|about|magnet|ftp):/i;
    const PROTOCOL_RELATIVE_RE = /^\/\//;
    const PATTERN_CHARS_RE = /[\*\?\(\)\[\]\{\}\\<>]/;
    const ENCODED_SUSPICIOUS_RE = /%5[bB]|%5[dD]|%7[bB]|%7[dD]|%3[cC]|%3[eE]/; // encoded brackets/angles
    const TRIVIAL_STATE_RE = /(self\.__next|__NEXT_DATA__|__PRELOADED_STATE__|window\.__PRELOADED__|{\s*")/i;

    function safeDecode(s) {
        try { return decodeURIComponent(s); } catch { return s; }
    }

    function normalizeUrl(raw, baseHref) {
        if (!raw || typeof raw !== 'string') return null;
        let s = raw.trim();

        if (s.length === 0 || s.length > cfg.maxUrlLength) return null;
        if (TRIVIAL_STATE_RE.test(s)) return null;
        if (PATTERN_CHARS_RE.test(s)) return null;

        // small sanity cleans
        s = s.replace(/\r\n|\n|\t/g, ''); // remove control whitespace
        s = s.replace(/&amp;/gi, '&');

        // quick junk schemes
        if (JUNK_SCHEME_RE.test(s)) return null;

        // protocol-relative -> add protocol
        if (PROTOCOL_RELATIVE_RE.test(s)) {
            if (cfg.followProtocolRelative) s = window.location.protocol + s;
            else return null;
        }

        // remove surrounding quotes
        if ((s.startsWith('"') && s.endsWith('"')) || (s.startsWith("'") && s.endsWith("'"))) {
            s = s.slice(1, -1);
        }

        // try building URL
        let urlObj;
        try {
            urlObj = new URL(s, baseHref || location.href);
        } catch {
            return null;
        }

        // only http/https allowed
        if (urlObj.protocol !== 'http:' && urlObj.protocol !== 'https:') return null;

        // Filter out static assets
        // We exclude xml (sitemaps) and json (data) from this hard filter to ensure discovery isn't hindered.
        const STATIC_EXTENSIONS = [
            'js', 'css', 'map',
            'png', 'jpg', 'jpeg', 'gif', 'svg', 'ico', 'webp', 'bmp', 'tiff',
            'woff', 'woff2', 'ttf', 'eot', 'otf',
            'mp3', 'mp4', 'wav', 'webm', 'ogg', 'flac',
            'zip', 'tar', 'gz', 'rar', '7z',
            'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'rtf', 'txt', 'csv'
        ];
        const STATIC_EXT_RE = new RegExp(`\\.(${STATIC_EXTENSIONS.join('|')})$`, 'i');

        if (STATIC_EXT_RE.test(urlObj.pathname)) return null;

        // avoid encoded suspicious characters and spaces in path
        if (ENCODED_SUSPICIOUS_RE.test(urlObj.href)) return null;
        if (safeDecode(urlObj.pathname || '').includes(' ')) return null;

        // remove fragment if configured
        if (cfg.stripFragment) urlObj.hash = '';

        // normalize host (punycode could be present, keep URL object behavior)
        urlObj.hostname = urlObj.hostname.toLowerCase();

        // remove default ports
        if ((urlObj.protocol === 'http:' && (urlObj.port === '80')) ||
            (urlObj.protocol === 'https:' && (urlObj.port === '443'))) {
            urlObj.port = '';
        }

        // collapse duplicate slashes in pathname
        urlObj.pathname = urlObj.pathname.replace(/\/{2,}/g, '/');

        // remove trailing slash unless root path
        let final = urlObj.href;
        try {
            const path = urlObj.pathname || '';
            if (final.endsWith('/') && path !== '/') {
                final = final.replace(/\/+$/, '');
            }
        } catch { /* ignore */ }

        // final length guard
        if (final.length > cfg.maxUrlLength) return null;

        return final;
    }

    function addCandidate(raw, baseHref) {
        const norm = normalizeUrl(raw, baseHref);
        if (!norm) return;
        normalizedSet.add(norm);
    }

    function parseSrcset(srcset) {
        if (!srcset || typeof srcset !== 'string') return [];
        try {
            return srcset.split(',').map(p => p.trim().split(/\s+/)[0]).filter(Boolean);
        } catch { return []; }
    }

    // 1. attribute-driven scanning
    (function scanAttributes() {
        const selector = [
            'a[href]', 'link[href]', 'area[href]',
            'img[src]', 'img[srcset]', 'iframe[src]',
            'script[src]', 'source[src]', 'video[src]', 'audio[src]',
            '[poster]', '[data-src]', '[data-href]', '[data-url]', '[formaction]'
        ].join(',');
        try {
            document.querySelectorAll(selector).forEach(el => {
                try {
                    if (el.hasAttribute('href')) addCandidate(el.getAttribute('href'));
                    if (el.hasAttribute('src')) addCandidate(el.getAttribute('src'));
                    if (el.hasAttribute('poster')) addCandidate(el.getAttribute('poster'));
                    if (el.hasAttribute('data-src')) addCandidate(el.getAttribute('data-src'));
                    if (el.hasAttribute('data-href')) addCandidate(el.getAttribute('data-href'));
                    if (el.hasAttribute('data-url')) addCandidate(el.getAttribute('data-url'));
                    if (el.hasAttribute('formaction')) addCandidate(el.getAttribute('formaction'));
                    if (el.hasAttribute('srcset')) parseSrcset(el.getAttribute('srcset')).forEach(u => addCandidate(u));
                    if (el.tagName.toLowerCase() === 'source' && el.hasAttribute('srcset')) parseSrcset(el.getAttribute('srcset')).forEach(u => addCandidate(u));
                } catch { /* ignore element-level errors */ }
            });
        } catch { /* ignore DOM access errors */ }
    })();

    // 2. scan data-/framework- attributes & inline attributes
    (function scanAllAttributes() {
        try {
            document.querySelectorAll('*').forEach(el => {
                try {
                    for (const attr of el.attributes) {
                        const name = attr.name.toLowerCase();
                        const val = attr.value;
                        if (!val || typeof val !== 'string') continue;
                        if (/href|src|url|data-|route|link|action|formaction|manifest|icon|poster|background|srcset/i.test(name)) {
                            addCandidate(val);
                        }
                        // inline handlers: extract direct location assignments or quoted URLs
                        if (/^on/i.test(name)) {
                            const matches = Array.from(val.matchAll(/(?:location(?:\.href)?|window\.location|document\.location)\s*=\s*['"]([^'"]+)['"]/gi));
                            matches.forEach(m => addCandidate(m[1]));
                            const fetchMatches = Array.from(val.matchAll(/fetch\(\s*['"]([^'"]+)['"]/gi)).map(m => m[1]);
                            fetchMatches.forEach(u => addCandidate(u));
                        }
                        // small heuristic: JSON-like attr contents with http substrings
                        if (val.includes('http') && val.length < 1000) {
                            const inner = Array.from(val.matchAll(/https?:\/\/[^\s'"]+/gi)).map(m => m[0]);
                            inner.forEach(u => addCandidate(u));
                        }
                    }
                } catch { /* ignore attribute-level */ }
            });
        } catch { /* ignore */ }
    })();

    // 3. embedded CSS and inline styles
    (function scanCSS() {
        try {
            document.querySelectorAll('style').forEach(tag => {
                const text = tag.textContent || '';
                const matches = Array.from(text.matchAll(/url\((?:["']?)([^"')]+)(?:["']?)\)/gi)).map(m => m[1]);
                matches.forEach(u => addCandidate(u));
            });
            document.querySelectorAll('[style]').forEach(el => {
                const styleVal = el.getAttribute('style') || '';
                const matches = Array.from(styleVal.matchAll(/url\((?:["']?)([^"')]+)(?:["']?)\)/gi)).map(m => m[1]);
                matches.forEach(u => addCandidate(u));
            });
        } catch { /* ignore CSS scan errors */ }
    })();

    // 4. scripts & JSON-LD strings
    (function scanScriptsAndJsonLD() {
        try {
            document.querySelectorAll('script').forEach(script => {
                try {
                    const type = (script.getAttribute('type') || '').toLowerCase();
                    const txt = script.textContent || '';
                    if (type === 'application/ld+json') {
                        try {
                            const parsed = JSON.parse(txt);
                            (function extractFromObject(obj, depth = 0) {
                                if (!obj || depth > 8) return;
                                if (typeof obj === 'string') {
                                    if (obj.includes('http')) {
                                        const matches = Array.from(obj.matchAll(/https?:\/\/[^\s'"]+/gi)).map(m => m[0]);
                                        matches.forEach(u => addCandidate(u));
                                    }
                                    return;
                                }
                                if (Array.isArray(obj)) { for (const it of obj) extractFromObject(it, depth + 1); return; }
                                if (typeof obj === 'object') { for (const k in obj) try { extractFromObject(obj[k], depth + 1); } catch { } }
                            })(parsed);
                        } catch { /* invalid JSON-LD ignored */ }
                    }
                    // find quoted URL strings and raw http matches inside JS
                    Array.from(txt.matchAll(/['"]((?:https?:)?\/\/[^'"]+)['"]/gi)).map(m => m[1]).forEach(u => addCandidate(u));
                    Array.from(txt.matchAll(/https?:\/\/[^\s'"`<>()]+/gi)).map(m => m[0]).forEach(u => addCandidate(u));
                } catch { /* ignore per-script */ }
            });
        } catch { /* ignore scripts scan */ }
    })();

    // 5. performance resources
    (function scanPerformanceResources() {
        try {
            if (window.performance && typeof performance.getEntriesByType === 'function') {
                performance.getEntriesByType('resource').forEach(r => { try { if (r && r.name) addCandidate(r.name); } catch { } });
            }
        } catch { /* ignore */ }
    })();

    // 6. anchors, sitemaps, location/history
    (function scanAnchorsAndLocation() {
        try {
            document.querySelectorAll('a[href]').forEach(a => { try { addCandidate(a.getAttribute('href')); } catch { } });
            addCandidate(location.href);
            try { if (history && history.state) { const s = JSON.stringify(history.state || {}); if (s) Array.from(s.matchAll(/https?:\/\/[^\s'"]+/gi)).map(m => m[0]).forEach(u => addCandidate(u)); } } catch { }
            try {
                const origin = location.origin;
                addCandidate(`${origin}/sitemap.xml`);
                addCandidate(`${origin}/sitemap_index.xml`);
            } catch { }
        } catch { }
    })();

    // 7. small, controlled runtime object scan (conservative)
    (function scanRuntimeObjects() {
        try {
            const visited = new WeakSet();
            let seen = 0;
            const roots = ['window', 'document', 'location', 'history', 'performance'];
            const queue = [];
            roots.forEach(r => { try { if (window[r]) queue.push(window[r]); } catch { } });

            let depth = 0;
            while (queue.length && depth <= cfg.maxRuntimeDepth && seen < cfg.maxRuntimeObjects) {
                const next = queue.shift();
                if (!next || typeof next !== 'object') { depth++; continue; }
                if (visited.has(next)) continue;
                visited.add(next);
                seen++;

                try {
                    for (const k in next) {
                        if (!Object.prototype.hasOwnProperty.call(next, k)) continue;
                        if (seen >= cfg.maxRuntimeObjects) break;
                        try {
                            const val = next[k];
                            if (typeof val === 'string' && val.length < 2000 && val.includes('/') && (val.startsWith('http') || val.startsWith('//') || val.indexOf('/') > -1)) {
                                Array.from(String(val).matchAll(/https?:\/\/[^\s'"]+/gi)).map(m => m[0]).forEach(u => addCandidate(u));
                            } else if (typeof val === 'object' && val !== null) {
                                queue.push(val);
                            }
                        } catch { }
                    }
                } catch { }
                depth++;
            }
        } catch { }
    })();

    // post-process & return: deterministic sorted array
    try {
        const arr = Array.from(normalizedSet);
        arr.sort((a, b) => a.localeCompare(b));
        return arr;
    } catch (e) {
        // On catastrophic failure, return empty array (script must return array only)
        return [];
    }
})();
