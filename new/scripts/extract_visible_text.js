/**
 * Extracts all visible text from the page.
 * Ignores script, style, meta, and hidden elements.
 * Returns a single string with readable formatting.
 */
(() => {
    const isVisible = (elem) => {
        const style = window.getComputedStyle(elem);
        return (
            style &&
            style.display !== "none" &&
            style.visibility !== "hidden" &&
            style.opacity !== "0" &&
            elem.offsetParent !== null
        );
    };

    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT, {
        acceptNode: (node) => (isVisible(node) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT),
    });

    let node;
    const lines = [];

    while ((node = walker.nextNode())) {
        const text = node.innerText || "";
        if (text.trim()) {
            lines.push(text.trim());
        }
    }

    return lines.join("\n\n"); // separate blocks with double newline
})();
