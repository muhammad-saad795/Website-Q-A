(() => {
    const isVisible = (el) => {
        if (!el || el.nodeType !== 1) return true;
        const s = getComputedStyle(el);
        return (
            s.display !== "none" &&
            s.visibility !== "hidden" &&
            s.opacity !== "0"
        );
    };

    const walker = document.createTreeWalker(
        document.body,
        NodeFilter.SHOW_TEXT,
        {
            acceptNode(node) {
                const parent = node.parentElement;
                if (!parent) return NodeFilter.FILTER_REJECT;
                if (!isVisible(parent)) return NodeFilter.FILTER_REJECT;

                const text = node.nodeValue.trim();
                if (!text) return NodeFilter.FILTER_REJECT;

                return NodeFilter.FILTER_ACCEPT;
            }
        }
    );

    const chunks = [];
    let node;

    while ((node = walker.nextNode())) {
        chunks.push(node.nodeValue.trim());
    }

    return chunks.join("\n");
})();
