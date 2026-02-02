/**
 * Enhanced Lazy-Loading Scroller.
 * Iteratively scrolls through the entire page to trigger lazy-loaded images, 
 * infinite scrolls, and dynamic content.
 */

(async () => {
    const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));

    const WAIT_AFTER_STEP = 250;     // Wait after each segment
    const WAIT_AT_BOTTOM = 1500;    // Wait for new content to trigger at the bottom
    const MAX_SCROLL_ATTEMPTS = 100; // Safety cap
    const VIEWPORT_PERCENT = 0.7;   // Scroll by 70% of viewport each time

    try {
        let lastHeight = document.body.scrollHeight;
        let attempts = 0;
        let reachedBottom = false;

        while (attempts < MAX_SCROLL_ATTEMPTS) {
            let currentPosition = window.scrollY + (window.innerHeight * VIEWPORT_PERCENT);
            window.scrollTo(0, currentPosition);
            await sleep(WAIT_AFTER_STEP);

            // Check if we are at the bottom of the current document
            if ((window.innerHeight + window.scrollY) >= document.body.scrollHeight - 5) {
                // We hit the bottom, but wait to see if more content loads
                await sleep(WAIT_AT_BOTTOM);

                const newHeight = document.body.scrollHeight;
                if (newHeight > lastHeight) {
                    lastHeight = newHeight;
                    // Reset or continue as the page grew
                    continue;
                } else {
                    // Page didn't grow after a solid wait at bottom
                    reachedBottom = true;
                    break;
                }
            }

            attempts++;
        }

        // One final jump to absolute bottom just in case
        window.scrollTo(0, document.body.scrollHeight);
        await sleep(500);

        // Scroll back to top for further processing (like layout snapshots or text extraction)
        window.scrollTo({ top: 0, behavior: 'auto' });
        await sleep(500);

    } catch (err) {
        console.warn("Enhanced Scroll Error:", err);
    }
})();
