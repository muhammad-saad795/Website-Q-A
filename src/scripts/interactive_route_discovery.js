(async () => {
    const delay = ms => new Promise(r => setTimeout(r, ms));

    const discovered = new Set();
    const originalUrl = location.href;

    const isVisible = el => {
        const r = el.getBoundingClientRect();
        return (
            r.width > 0 &&
            r.height > 0 &&
            r.bottom > 0 &&
            r.right > 0 &&
            getComputedStyle(el).visibility !== "hidden"
        );
    };

    const candidates = Array.from(
        document.querySelectorAll(`
            [role="menuitem"],
            [role="button"],
            nav li,
            nav div
        `)
    ).filter(el =>
        isVisible(el) &&
        !el.hasAttribute("disabled") &&
        el.getAttribute("aria-disabled") !== "true"
    );

    for (const el of candidates) {
        try {
            const before = location.href;

            el.click();
            await delay(600);

            const after = location.href;

            if (after !== before) {
                discovered.add(after);
                history.back();
                await delay(600);
            }
        } catch { }
    }

    // Ensure original page restored
    if (location.href !== originalUrl) {
        location.href = originalUrl;
        await delay(600);
    }

    return {
        total: discovered.size,
        urls: Array.from(discovered)
    };
})();
