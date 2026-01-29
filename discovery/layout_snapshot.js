(() => {
    const viewport = {
        width: window.innerWidth,
        height: window.innerHeight
    };

    const INTERACTIVE_SELECTOR = `
    button,
    a,
    input,
    select,
    textarea,
    [role="button"]
  `;

    const CONTAINER_SELECTOR = `
    div,
    section,
    article,
    main,
    header,
    footer,
    nav
  `;

    const seen = new Set();
    const snapshots = [];

    function isVisible(style, rect) {
        return (
            style.display !== 'none' &&
            style.visibility !== 'hidden' &&
            parseFloat(style.opacity) > 0 &&
            rect.width > 0 &&
            rect.height > 0
        );
    }

    function isInViewport(rect) {
        return (
            rect.bottom > 0 &&
            rect.right > 0 &&
            rect.top < viewport.height &&
            rect.left < viewport.width
        );
    }

    function isInteractive(el) {
        return el.matches(INTERACTIVE_SELECTOR);
    }

    function capture(el) {
        if (!el || seen.has(el)) return;
        seen.add(el);

        const rect = el.getBoundingClientRect();
        const style = window.getComputedStyle(el);

        const visible = isVisible(style, rect);
        if (!visible) return;

        const snapshot = {
            tag: el.tagName.toLowerCase(),
            id: el.id || null,
            classes: [...el.classList],
            role: el.getAttribute('role'),
            text: el.innerText?.slice(0, 120) || null,
            tabIndex: el.tabIndex,

            rect: {
                x: rect.x,
                y: rect.y,
                width: rect.width,
                height: rect.height
            },

            viewport,

            computed: {
                display: style.display,
                visibility: style.visibility,
                position: style.position,
                opacity: style.opacity,
                overflow: style.overflow,
                zIndex: style.zIndex,
                pointerEvents: style.pointerEvents,
                color: style.color,
                backgroundColor: style.backgroundColor,
                fontSize: style.fontSize,
                marginTop: style.marginTop,
                marginBottom: style.marginBottom,
                marginLeft: style.marginLeft,
                marginRight: style.marginRight,
                paddingTop: style.paddingTop,
                paddingBottom: style.paddingBottom,
                paddingLeft: style.paddingLeft,
                paddingRight: style.paddingRight,
                borderTopWidth: style.borderTopWidth,
                borderBottomWidth: style.borderBottomWidth,
                borderLeftWidth: style.borderLeftWidth,
                borderRightWidth: style.borderRightWidth
            },

            flags: {
                isVisible: visible,
                isInViewport: isInViewport(rect),
                isClickable:
                    visible &&
                    style.pointerEvents !== 'none' &&
                    isInViewport(rect),
                isInteractive: isInteractive(el)
            },

            parent: null
        };

        const parent = el.parentElement;
        if (parent) {
            const prect = parent.getBoundingClientRect();
            snapshot.parent = {
                tag: parent.tagName.toLowerCase(),
                id: parent.id || null,
                rect: {
                    x: prect.x,
                    y: prect.y,
                    width: prect.width,
                    height: prect.height
                }
            };
        }

        snapshots.push(snapshot);
    }

    // 1️⃣ Interactive first (highest QA value)
    document.querySelectorAll(INTERACTIVE_SELECTOR).forEach(capture);

    // 2️⃣ Visible containers
    document.querySelectorAll(CONTAINER_SELECTOR).forEach(capture);

    return {
        viewport,
        elements: snapshots,
        timestamp: Date.now()
    };
})();
