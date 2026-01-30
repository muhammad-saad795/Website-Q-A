(() => {
    const discovered = new Set();
    const visitedObjects = new WeakSet();

    const normalize = (url) => {
        try {
            return new URL(url, location.href).href;
        } catch {
            return null;
        }
    };

    const add = (url) => {
        const n = normalize(url);
        if (n) discovered.add(n);
    };

    /* ─────────────────────────────────────────────
       1️⃣ DOM-based URLs
    ───────────────────────────────────────────── */
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
    `).forEach(el => {
        add(el.getAttribute("href") || el.getAttribute("src"));
    });

    /* ─────────────────────────────────────────────
       2️⃣ Data attributes (lazy / SPA routing)
    ───────────────────────────────────────────── */
    document.querySelectorAll("*").forEach(el => {
        [...el.attributes].forEach(attr => {
            if (/url|href|src|link|route/i.test(attr.name)) {
                add(attr.value);
            }
        });
    });

    /* ─────────────────────────────────────────────
       3️⃣ Inline JS navigation (onclick, onsubmit)
    ───────────────────────────────────────────── */
    document.querySelectorAll("[onclick],[onsubmit]").forEach(el => {
        const code = el.getAttribute("onclick") || el.getAttribute("onsubmit");
        if (!code) return;

        // window.location / location.href / assign / replace
        const matches = code.match(/(?:location(?:\.href)?|window\.location)\s*=\s*['"]([^'"]+)['"]/g);
        if (matches) {
            matches.forEach(m => {
                const url = m.match(/['"]([^'"]+)['"]/)?.[1];
                add(url);
            });
        }
    });

    /* ─────────────────────────────────────────────
       4️⃣ SPA router detection (React, Vue, Angular)
    ───────────────────────────────────────────── */
    try {
        if (window.__REACT_DEVTOOLS_GLOBAL_HOOK__) {
            document.querySelectorAll("a").forEach(a => add(a.href));
        }

        if (window.__VUE_DEVTOOLS_GLOBAL_HOOK__) {
            document.querySelectorAll("a").forEach(a => add(a.href));
        }

        if (window.angular) {
            document.querySelectorAll("[ng-href]").forEach(el => {
                add(el.getAttribute("ng-href"));
            });
        }
    } catch { }

    /* ─────────────────────────────────────────────
       5️⃣ Runtime JS object graph scan
       (deep scan but safe)
    ───────────────────────────────────────────── */
    const scanObject = (obj, depth = 0) => {
        if (!obj || typeof obj !== "object") return;
        if (visitedObjects.has(obj)) return;
        if (depth > 4) return;

        visitedObjects.add(obj);

        for (const key in obj) {
            try {
                const value = obj[key];

                if (typeof value === "string" && value.includes("/")) {
                    add(value);
                } else if (typeof value === "object") {
                    scanObject(value, depth + 1);
                }
            } catch { }
        }
    };

    try {
        scanObject(window);
    } catch { }

    /* ─────────────────────────────────────────────
       6️⃣ Performance API (fetch/XHR/JS-loaded)
    ───────────────────────────────────────────── */
    performance.getEntriesByType("resource").forEach(r => {
        add(r.name);
    });

    /* ─────────────────────────────────────────────
       7️⃣ History & SPA state
    ───────────────────────────────────────────── */
    add(location.href);
    if (history.state) {
        try {
            scanObject(history.state);
        } catch { }
    }

    /* ─────────────────────────────────────────────
       FINAL OUTPUT
    ───────────────────────────────────────────── */
    return {
        total: discovered.size,
        urls: Array.from(discovered).sort()
    };
})();
