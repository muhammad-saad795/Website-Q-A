(() => {
    const discovered = new Set();
    const visitedObjects = new WeakSet();

    const normalize = (url) => {
        if (!url || typeof url !== "string") return null;

        // 1. Initial length check for sanity
        if (url.length > 1000) return null;

        // 2. Clear known junk markers (serialized code/state)
        if (url.includes('self.__next_f') || url.includes('{"') || url.includes('["')) return null;

        url = url.trim()
            .replace(/[\r\n\t]+/g, "")      // remove newlines/tabs
            .replace(/&amp;/gi, "&");       // decode basic HTML entities

        // 3. Skip non-web schemes
        if (/^(javascript|data|mailto|tel):/i.test(url)) return null;

        try {
            const absoluteUrl = new URL(url, location.href);

            // Only allow http/https
            if (absoluteUrl.protocol !== 'http:' && absoluteUrl.protocol !== 'https:') return null;

            // Remove hash/fragment for discovery purposes
            absoluteUrl.hash = "";

            let finalUrl = absoluteUrl.href.replace(/\/+$/, "");

            // 4. Strict path validation (avoid leaked JS code being treated as paths)
            // Paths with spaces, quotes, or balanced braces are almost always junk
            const decodedPath = decodeURIComponent(absoluteUrl.pathname);
            if (/["'\[\]{}()|<>]/.test(decodedPath)) return null;
            if (decodedPath.includes(' ')) return null;

            return finalUrl;
        } catch {
            return null;
        }
    };

    const add = (url) => {
        const n = normalize(url);
        if (n && n.length < 2048) {
            discovered.add(n);
        }
    };


    /* ───── 1️⃣ DOM-based URLs ───── */
    document.querySelectorAll(`
        a[href],
        link[href],
        area[href],
        iframe[src],
        img[src],
        script[src],
        source[src],
        video[src],
        audio[src]
    `).forEach(el => add(el.getAttribute("href") || el.getAttribute("src")));

    /* ───── 2️⃣ Data attributes (lazy/SPAs) ───── */
    document.querySelectorAll("*").forEach(el => {
        [...el.attributes].forEach(attr => {
            if (/url|href|src|link|route/i.test(attr.name)) add(attr.value);
        });
    });

    /* ───── 3️⃣ Inline JS navigation ───── */
    document.querySelectorAll("[onclick],[onsubmit]").forEach(el => {
        const code = el.getAttribute("onclick") || el.getAttribute("onsubmit");
        if (!code) return;

        const matches = [...code.matchAll(/(?:location(?:\.href)?|window\.location)\s*=\s*['"]([^'"]+)['"]/gi)];
        matches.forEach(m => add(m[1]));
    });

    /* ───── 4️⃣ SPA router detection ───── */
    try {
        if (window.__REACT_DEVTOOLS_GLOBAL_HOOK__ || window.__VUE_DEVTOOLS_GLOBAL_HOOK__) {
            document.querySelectorAll("a[href]").forEach(a => add(a.href));
        }
        if (window.angular) {
            document.querySelectorAll("[ng-href]").forEach(el => add(el.getAttribute("ng-href")));
        }
    } catch { }

    /* ───── 5️⃣ Runtime JS object graph scan ───── */
    const scanObject = (obj, depth = 0) => {
        if (!obj || typeof obj !== "object") return;
        if (visitedObjects.has(obj) || depth > 4) return;
        visitedObjects.add(obj);

        for (const key in obj) {
            try {
                const value = obj[key];
                if (typeof value === "string" && value.includes("/")) add(value);
                else if (typeof value === "object") scanObject(value, depth + 1);
            } catch { }
        }
    };
    try { scanObject(window); } catch { }

    /* ───── 6️⃣ Performance API (JS-loaded resources) ───── */
    performance.getEntriesByType("resource").forEach(r => add(r.name));

    /* ───── 7️⃣ Current page & history state ───── */
    add(location.href);
    if (history.state) try { scanObject(history.state); } catch { }

    /* ───── FINAL OUTPUT ───── */
    return {
        total: discovered.size,
        urls: Array.from(discovered).sort()
    };
})();
