(() => {
    if (window.__DISCOVERED_DOM_URLS__) return;

    window.__DISCOVERED_DOM_URLS__ = new Set();

    const ATTRS = ["href", "src", "action"];

    function extractFromElement(el) {
        if (!el || !el.getAttribute) return;

        for (const attr of ATTRS) {
            const val = el.getAttribute(attr);
            if (val && typeof val === "string") {
                window.__DISCOVERED_DOM_URLS__.add(val);
            }
        }
    }

    function deepScan(node) {
        if (!node) return;
        extractFromElement(node);

        if (node.querySelectorAll) {
            node.querySelectorAll("*").forEach(extractFromElement);
        }
    }

    // Initial DOM scan
    document.querySelectorAll("*").forEach(extractFromElement);

    // Observe runtime DOM mutations
    new MutationObserver(mutations => {
        for (const m of mutations) {
            if (m.type === "attributes") {
                extractFromElement(m.target);
            }

            if (m.addedNodes && m.addedNodes.length) {
                m.addedNodes.forEach(deepScan);
            }
        }
    }).observe(document.documentElement, {
        childList: true,
        subtree: true,
        attributes: true
    });
})();
