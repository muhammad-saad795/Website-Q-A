// new/scripts/layout_auditor.js
// Production-grade layout auditor to be executed inside page.evaluate(...).
// Returns a plain JSON object summary: { status, metrics, violations, errors, config_used }
// Config can be provided on the page via:
//   window.__LAYOUT_AUDITOR_CONFIG (object) OR
//   <html data-layout-auditor='{"overlapThreshold":0.05,...}'>
// Keys supported (all optional):
//   criticalSelectors: array of selectors (default: ["[data-critical]","main","header","nav","footer","[data-qa]"]),
//   overlapThreshold: fraction of min(areaA,areaB) to count as meaningful overlap (default 0.04),
//   overlapMinPx: minimum pixel intersection on each axis to count (default 6),
//   overflowTolerancePx: allow small scroll diff (default 4),
//   ignoreInvisible: true,
//   maxElementsToScan: 2000,
//   allowlists: { selectors: [...], attrs: { allowAbsolute: "data-allow-absolute", allowOffscreen: "data-allow-offscreen", allowZero: "data-allow-zero" } }
//   waitForMillis: how long to wait for fonts/images (default 1200)
//   maxReportItems: maximum returned violation entries (default 300)

(async function layoutAuditor() {
    const timeStart = Date.now();
    const defaultConfig = {
        criticalSelectors: ["[data-critical]", "main", "header", "nav", "footer", "[data-qa]", "[role='main']", ".container", ".page"],
        overlapThreshold: 0.04, // intersection area / min(areaA,areaB)
        overlapMinPx: 6, // minimum px overlap on both width and height
        overflowTolerancePx: 4,
        ignoreInvisible: true,
        maxElementsToScan: 3000,
        allowlists: {
            selectors: [], // elements matching these selectors are ignored entirely
            attrs: {
                allowAbsolute: "data-allow-absolute",
                allowOffscreen: "data-allow-offscreen",
                allowZero: "data-allow-zero"
            }
        },
        waitForMillis: 1200,
        maxReportItems: 500
    };

    function readConfig() {
        try {
            if (window.__LAYOUT_AUDITOR_CONFIG && typeof window.__LAYOUT_AUDITOR_CONFIG === "object") {
                return Object.assign({}, defaultConfig, window.__LAYOUT_AUDITOR_CONFIG);
            }
            const attr = document.documentElement.getAttribute("data-layout-auditor");
            if (attr) {
                try {
                    const parsed = JSON.parse(attr);
                    return Object.assign({}, defaultConfig, parsed);
                } catch (e) {
                    // fallthrough
                }
            }
        } catch (e) {
            // noop
        }
        return defaultConfig;
    }

    const config = readConfig();

    // Utility: safe sampling / limit large NodeLists
    function toArrayLimited(list, limit = 1000) {
        const arr = Array.from(list || []);
        if (arr.length > limit) return arr.slice(0, limit);
        return arr;
    }

    // Wait for fonts and visible images to settle up to timeout
    async function settleVisuals(waitMillis) {
        const imgs = Array.from(document.images || []);
        const imgPromises = imgs.map(img => {
            // if loaded or complete ok -> resolved
            if (img.complete) return Promise.resolve();
            return new Promise(res => {
                const t = setTimeout(() => {
                    res(); // timeout, resolve anyway
                }, waitMillis);
                img.addEventListener("load", () => { clearTimeout(t); res(); }, { once: true });
                img.addEventListener("error", () => { clearTimeout(t); res(); }, { once: true });
            });
        });

        // wait for fonts if supported
        const fontPromise = (document.fonts && document.fonts.ready) ? document.fonts.ready : Promise.resolve();
        try {
            await Promise.race([Promise.all(imgPromises.concat([fontPromise])), new Promise(r => setTimeout(r, waitMillis))]);
        } catch (e) {
            // swallow
        }
    }

    // Safe retrieval of computed style
    function safeStyle(el) {
        try { return window.getComputedStyle(el); } catch (e) { return null; }
    }

    // Visibility test: excludes elements that are display:none, visibility:hidden, opacity ~0, or zero-area (optionally)
    function isVisiblyRendered(el) {
        if (!el) return false;
        // skip nodes not in document
        if (!document.documentElement.contains(el)) return false;
        const s = safeStyle(el);
        if (!s) return false;
        if (s.display === "none" || s.visibility === "hidden") return false;
        const op = parseFloat(s.opacity || "1");
        if (op < 0.02) return false;
        const rects = el.getClientRects();
        if (!rects || rects.length === 0) return false;
        // check bounding rect
        const r = el.getBoundingClientRect();
        if (r.width === 0 && r.height === 0) return false;
        return true;
    }

    // Build unique-ish selector path for reporting
    function cssPath(el) {
        if (!el || el.nodeType !== 1) return "";
        const parts = [];
        let node = el;
        while (node && node.nodeType === 1 && node !== document.documentElement) {
            let part = node.tagName.toLowerCase();
            if (node.id) {
                part += `#${node.id}`;
                parts.unshift(part);
                break;
            } else {
                // add nth-child if there are siblings with same tag
                const parent = node.parentNode;
                if (!parent) {
                    parts.unshift(part);
                } else {
                    const same = Array.from(parent.children).filter(c => c.tagName === node.tagName);
                    if (same.length > 1) {
                        const idx = Array.prototype.indexOf.call(parent.children, node) + 1;
                        part += `:nth-child(${idx})`;
                    }
                    parts.unshift(part);
                }
            }
            node = node.parentNode;
        }
        parts.unshift("html");
        return parts.join(" > ");
    }

    // Serialize small html snippet (safe truncation)
    function snippet(el, max = 240) {
        try {
            const s = el.outerHTML || el.tagName;
            return s.length > max ? s.slice(0, max) + "…" : s;
        } catch (e) {
            return el.tagName || "<unknown>";
        }
    }

    // Cross-origin iframe detection helper: returns { ok: bool, reason? }
    function iframeAccessCheck(iframe) {
        try {
            // attempt to read contentDocument; will throw for cross-origin
            const doc = iframe.contentDocument;
            if (!doc) return { ok: false, reason: "no contentDocument" };
            return { ok: true };
        } catch (e) {
            return { ok: false, reason: "cross-origin or blocked" };
        }
    }

    // Geometry helpers
    function areaOf(rect) {
        return Math.max(0, rect.width) * Math.max(0, rect.height);
    }
    function rectIntersection(a, b) {
        const left = Math.max(a.left, b.left);
        const right = Math.min(a.right, b.right);
        const top = Math.max(a.top, b.top);
        const bottom = Math.min(a.bottom, b.bottom);
        const width = Math.max(0, right - left);
        const height = Math.max(0, bottom - top);
        return { width, height, area: width * height, left, top, right, bottom };
    }

    // main scanning function
    try {
        await settleVisuals(config.waitForMillis || 800);
    } catch (e) {
        // ignore
    }

    const viewport = { width: Math.max(0, window.innerWidth || 0), height: Math.max(0, window.innerHeight || 0) };
    const report = { status: "pass", metrics: {}, violations: [], errors: [], config_used: config };

    // collect candidate elements
    let candidates = [];
    try {
        const selectors = config.criticalSelectors && config.criticalSelectors.length ? config.criticalSelectors : defaultConfig.criticalSelectors;
        const seen = new Set();
        for (const sel of selectors) {
            try {
                const nodes = toArrayLimited(document.querySelectorAll(sel), config.maxElementsToScan || 1000);
                for (const n of nodes) {
                    if (!n || seen.has(n)) continue;
                    // honor global allowlist selectors
                    if (config.allowlists && Array.isArray(config.allowlists.selectors)) {
                        let skip = false;
                        for (const a of config.allowlists.selectors) {
                            try { if (n.matches && n.matches(a)) { skip = true; break; } } catch (e) { }
                        }
                        if (skip) continue;
                    }
                    seen.add(n);
                    candidates.push(n);
                }
            } catch (e) {
                // ignore invalid selector
            }
        }

        // If nothing matched critical selectors, fallback to heuristics: visible top-level interactive pieces
        if (candidates.length === 0) {
            const heur = ["header", "nav", "main", "article", "section", "footer", "[role='main']", "[role='navigation']", "[data-qa]"];
            for (const sel of heur) {
                const nodes = toArrayLimited(document.querySelectorAll(sel), Math.ceil((config.maxElementsToScan || 1000) / heur.length));
                for (const n of nodes) {
                    if (!n) continue;
                    candidates.push(n);
                }
            }
        }

        // final defensive cap
        if (candidates.length > (config.maxElementsToScan || 3000)) {
            candidates = candidates.slice(0, config.maxElementsToScan || 3000);
        }
    } catch (e) {
        report.errors.push({ stage: "collect", message: String(e) });
    }

    // filter and map to serializable metadata
    const nodesMeta = [];
    for (const el of candidates) {
        try {
            // skip invisible if config says so
            if (config.ignoreInvisible && !isVisiblyRendered(el)) continue;

            const rect = el.getBoundingClientRect();
            const cs = safeStyle(el) || {};
            const allowAbsolute = el.hasAttribute && el.hasAttribute(config.allowlists.attrs.allowAbsolute);
            const allowOffscreen = el.hasAttribute && el.hasAttribute(config.allowlists.attrs.allowOffscreen);
            const allowZero = el.hasAttribute && el.hasAttribute(config.allowlists.attrs.allowZero);

            nodesMeta.push({
                tag: el.tagName,
                selector: cssPath(el),
                snippet: snippet(el, 240),
                rect: {
                    left: Math.round(rect.left),
                    top: Math.round(rect.top),
                    right: Math.round(rect.right),
                    bottom: Math.round(rect.bottom),
                    width: Math.round(rect.width),
                    height: Math.round(rect.height)
                },
                styles: {
                    display: cs.display || "",
                    position: cs.position || "",
                    visibility: cs.visibility || "",
                    opacity: cs.opacity || "",
                    zIndex: (cs.zIndex || "").toString(),
                    fontSize: cs.fontSize || "",
                    lineHeight: cs.lineHeight || "",
                    overflowX: cs.overflowX || "",
                    overflowY: cs.overflowY || ""
                },
                allowAbsolute,
                allowOffscreen,
                allowZero,
                nodeReference: null // intentionally not serializable, placeholder
            });
        } catch (e) {
            // skip bad element
        }
    }

    // Overlap detection (pairwise but optimized): use grid bucketing to avoid N^2 explosion
    const overlaps = [];
    try {
        // build buckets
        const bucketSize = Math.max(250, Math.min(viewport.width, viewport.height, 600));
        const buckets = new Map();
        function bucketKey(x, y) { return `${x}:${y}`; }
        function addToBuckets(idx, r) {
            const minX = Math.floor(r.left / bucketSize);
            const maxX = Math.floor((r.right) / bucketSize);
            const minY = Math.floor(r.top / bucketSize);
            const maxY = Math.floor((r.bottom) / bucketSize);
            for (let bx = minX; bx <= maxX; bx++) {
                for (let by = minY; by <= maxY; by++) {
                    const k = bucketKey(bx, by);
                    if (!buckets.has(k)) buckets.set(k, []);
                    buckets.get(k).push(idx);
                }
            }
        }

        nodesMeta.forEach((m, i) => addToBuckets(i, m.rect));

        const reportedPairs = new Set();
        for (const [k, list] of buckets.entries()) {
            for (let i = 0; i < list.length; i++) {
                for (let j = i + 1; j < list.length; j++) {
                    const aIdx = list[i];
                    const bIdx = list[j];
                    if (aIdx === bIdx) continue;
                    const key = aIdx < bIdx ? `${aIdx}|${bIdx}` : `${bIdx}|${aIdx}`;
                    if (reportedPairs.has(key)) continue;
                    reportedPairs.add(key);
                    const a = nodesMeta[aIdx].rect;
                    const b = nodesMeta[bIdx].rect;
                    // ignore ancestor/descendant: if selector includes the other tag as ancestor prefix, skip
                    try {
                        // cheap check: if one selector string contains the other plus ' > ' assume ancestry (heuristic)
                        const sa = nodesMeta[aIdx].selector;
                        const sb = nodesMeta[bIdx].selector;
                        if (sa.includes(sb + " >") || sb.includes(sa + " >")) continue;
                    } catch (e) { }

                    const inter = rectIntersection(a, b);
                    if (inter.width < (config.overlapMinPx || 6) || inter.height < (config.overlapMinPx || 6)) continue;
                    const areaA = Math.max(1, areaOf(a));
                    const areaB = Math.max(1, areaOf(b));
                    const denom = Math.min(areaA, areaB);
                    const frac = denom > 0 ? inter.area / denom : 0;
                    if (frac >= (config.overlapThreshold || 0.04)) {
                        overlaps.push({
                            a: { selector: nodesMeta[aIdx].selector, snippet: nodesMeta[aIdx].snippet, rect: a },
                            b: { selector: nodesMeta[bIdx].selector, snippet: nodesMeta[bIdx].snippet, rect: b },
                            intersection: inter,
                            ratio: Number(frac.toFixed(4))
                        });
                    }
                }
            }
        }
    } catch (e) {
        report.errors.push({ stage: "overlap", message: String(e) });
    }

    // Text overflow detection: target text-like elements only to reduce noise
    const textOverflow = [];
    try {
        const textSelectors = ["p", "span", "h1", "h2", "h3", "h4", "h5", "h6", "a", "button", "li", ".btn", "[data-qa]"];
        const nodes = toArrayLimited(document.querySelectorAll(textSelectors.join(",")), config.maxElementsToScan || 2000);
        for (const el of nodes) {
            try {
                if (config.ignoreInvisible && !isVisiblyRendered(el)) continue;
                // skip elements that allow overflow intentionally (simple heuristic)
                const s = safeStyle(el);
                if (!s) continue;
                if (s.overflowX === "visible" && s.overflowY === "visible") continue;
                const scrollW = el.scrollWidth || 0;
                const clientW = el.clientWidth || 0;
                const scrollH = el.scrollHeight || 0;
                const clientH = el.clientHeight || 0;
                if (scrollW - clientW > (config.overflowTolerancePx || 4) || scrollH - clientH > (config.overflowTolerancePx || 4)) {
                    const text = (el.textContent || "").trim();
                    if (text.length < 6) continue; // ignore tiny text nodes
                    textOverflow.push({
                        selector: cssPath(el),
                        snippet: snippet(el, 180),
                        scrollWidth: scrollW,
                        clientWidth: clientW,
                        scrollHeight: scrollH,
                        clientHeight: clientH
                    });
                }
            } catch (e) {
                // ignore element errors
            }
        }
    } catch (e) {
        report.errors.push({ stage: "overflow", message: String(e) });
    }

    // Offscreen detection (unintentional)
    const offscreen = [];
    try {
        for (const m of nodesMeta) {
            try {
                if (m.allowOffscreen) continue;
                const r = m.rect;
                // if entirely outside viewport by more than a small tolerance, flag
                if (r.right < -8 || r.left > viewport.width + 8 || r.bottom < -8 || r.top > viewport.height + 8) {
                    offscreen.push({
                        selector: m.selector,
                        snippet: m.snippet,
                        rect: r
                    });
                }
            } catch (e) { }
        }
    } catch (e) {
        report.errors.push({ stage: "offscreen", message: String(e) });
    }

    // Zero-size elements that are expected to render
    const zeroSize = [];
    try {
        for (const m of nodesMeta) {
            try {
                if (m.allowZero) continue;
                if (m.rect.width <= 0 || m.rect.height <= 0) {
                    zeroSize.push({
                        selector: m.selector,
                        snippet: m.snippet,
                        rect: m.rect,
                        styles: m.styles
                    });
                }
            } catch (e) { }
        }
    } catch (e) {
        report.errors.push({ stage: "zerosize", message: String(e) });
    }

    // Absolute/fixed positioning abuse detection
    const absoluteAbuse = [];
    try {
        for (const m of nodesMeta) {
            try {
                const pos = (m.styles && m.styles.position) || "";
                if ((pos === "absolute" || pos === "fixed") && !m.allowAbsolute) {
                    // if element covers a meaningful part of viewport and overlaps others -> suspect
                    const area = Math.max(1, m.rect.width) * Math.max(1, m.rect.height);
                    const viewportArea = Math.max(1, viewport.width) * Math.max(1, viewport.height);
                    const coverage = area / viewportArea;
                    if (coverage > 0.3 || (m.rect.top < 0 || m.rect.left < 0 || m.rect.right > viewport.width || m.rect.bottom > viewport.height)) {
                        absoluteAbuse.push({
                            selector: m.selector,
                            snippet: m.snippet,
                            rect: m.rect,
                            coverage: Number(coverage.toFixed(3)),
                            position: pos
                        });
                    }
                }
            } catch (e) { }
        }
    } catch (e) {
        report.errors.push({ stage: "absolute", message: String(e) });
    }

    // Layout shift detection (performance API)
    let layoutShifts = 0;
    try {
        const entries = performance.getEntriesByType ? performance.getEntriesByType("layout-shift") : [];
        for (const e of entries || []) {
            if (!e.hadRecentInput) layoutShifts++;
        }
    } catch (e) {
        // ignore
    }

    // Iframe auditing: report cross-origin iframes as "unknown" and try to run simple checks on same-origin
    const iframeReports = [];
    try {
        const iframes = Array.from(document.querySelectorAll("iframe"));
        for (const iframe of iframes) {
            try {
                const access = iframeAccessCheck(iframe);
                const rect = iframe.getBoundingClientRect ? iframe.getBoundingClientRect() : { left: 0, top: 0, width: 0, height: 0, right: 0, bottom: 0 };
                if (!access.ok) {
                    iframeReports.push({ selector: cssPath(iframe), snippet: snippet(iframe, 160), rect: { left: Math.round(rect.left), top: Math.round(rect.top), width: Math.round(rect.width), height: Math.round(rect.height) }, crossOrigin: true, reason: access.reason });
                    continue;
                }
                // same-origin: attempt a minimal audit (titles/main existence)
                try {
                    const doc = iframe.contentDocument;
                    const body = doc && doc.body ? doc.body : null;
                    const hasMain = doc && (doc.querySelector && doc.querySelector("main"));
                    iframeReports.push({ selector: cssPath(iframe), snippet: snippet(iframe, 160), rect: { left: Math.round(rect.left), top: Math.round(rect.top), width: Math.round(rect.width), height: Math.round(rect.height) }, crossOrigin: false, hasMain: !!hasMain, bodyLength: body ? (body.innerText || "").length : 0 });
                } catch (e) {
                    iframeReports.push({ selector: cssPath(iframe), snippet: snippet(iframe, 160), rect: { left: Math.round(rect.left), top: Math.round(rect.top), width: Math.round(rect.width), height: Math.round(rect.height) }, crossOrigin: true, reason: "same-origin check failed" });
                }
            } catch (e) {
                // ignore iframe errors
            }
        }
    } catch (e) {
        report.errors.push({ stage: "iframe", message: String(e) });
    }

    // CSS explosion: count styleSheets and rules, tolerate cross-origin by catching errors
    let stylesheetCount = 0, cssRuleCount = 0;
    try {
        const s = document.styleSheets || [];
        stylesheetCount = s.length;
        for (const ss of s) {
            try {
                if (ss.cssRules) cssRuleCount += ss.cssRules.length;
            } catch (e) {
                // cross-origin stylesheet; ignore count but mark
                cssRuleCount += 0;
            }
        }
    } catch (e) {
        // ignore
    }

    // Compose metrics and final violations list with reasonable caps
    report.metrics = {
        scannedElements: nodesMeta.length,
        viewport,
        overlapsFound: overlaps.length,
        overflowFound: textOverflow.length,
        offscreenFound: offscreen.length,
        zeroSizeFound: zeroSize.length,
        absoluteAbuseFound: absoluteAbuse.length,
        layoutShifts,
        iframeCount: iframeReports.length,
        stylesheetCount,
        cssRuleCount,
        durationMs: Date.now() - timeStart
    };

    // Build violation entries in order of priority
    const violations = [];

    // overlaps high priority
    for (const o of overlaps.slice(0, config.maxReportItems || 500)) {
        violations.push({ type: "OVERLAP", detail: o });
    }
    // absolute abuse
    for (const a of absoluteAbuse.slice(0, Math.max(0, (config.maxReportItems || 500) - violations.length))) {
        violations.push({ type: "ABSOLUTE_ABUSE", detail: a });
    }
    // text overflow
    for (const t of textOverflow.slice(0, Math.max(0, (config.maxReportItems || 500) - violations.length))) {
        violations.push({ type: "TEXT_OVERFLOW", detail: t });
    }
    // offscreen
    for (const off of offscreen.slice(0, Math.max(0, (config.maxReportItems || 500) - violations.length))) {
        violations.push({ type: "OFFSCREEN", detail: off });
    }
    // zero-size
    for (const z of zeroSize.slice(0, Math.max(0, (config.maxReportItems || 500) - violations.length))) {
        violations.push({ type: "ZERO_SIZE", detail: z });
    }

    // include iframe reports and CSS metrics as informative entries (not necessarily violations)
    if (iframeReports.length) violations.push({ type: "IFRAME_SUMMARY", count: iframeReports.length, details: iframeReports.slice(0, 20) });
    violations.push({ type: "CSS_METRICS", stylesheetCount, cssRuleCount });

    // layout instability
    if (layoutShifts > 0) {
        violations.push({ type: "LAYOUT_SHIFTS", count: layoutShifts });
    }

    report.violations = violations.slice(0, config.maxReportItems || 500);
    report.status = (report.violations && report.violations.length > 0) ? "fail" : "pass";

    // final trimmed report (remove node references)
    return report;
})();