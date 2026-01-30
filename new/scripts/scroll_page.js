/**
 * Robust lazy-loading scroller.
 * Scrolls page down in increments, waits for new content, then scrolls back up.
 * Designed for infinite scroll and lazy-loaded content.
 */

(async () => {
    const SCROLL_STEP = 400;     // Pixels to scroll per step
    const WAIT_MS = 300;         // Wait after each scroll for content to load
    const MAX_ITERATIONS = 2000; // Safety limit to prevent infinite loop
    const BOTTOM_PAUSE_MS = 500; // Pause at the bottom

    const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));

    let lastHeight = document.body.scrollHeight;
    let iterations = 0;

    try {
        // Scroll down incrementally
        while (iterations < MAX_ITERATIONS) {
            window.scrollBy(0, SCROLL_STEP);
            await sleep(WAIT_MS);

            const newHeight = document.body.scrollHeight;
            if (newHeight === lastHeight) {
                break; // No new content loaded
            }
            lastHeight = newHeight;
            iterations++;
        }

        // Pause briefly at the bottom
        await sleep(BOTTOM_PAUSE_MS);

        // Scroll back up smoothly
        window.scrollTo({ top: 0, behavior: 'smooth' });

    } catch (err) {
        console.warn("Scroll script error:", err);
    }
})();
