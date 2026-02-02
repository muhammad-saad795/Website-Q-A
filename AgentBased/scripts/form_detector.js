(function () {
    function qsAll(root, sel) {
        try { return Array.from(root.querySelectorAll(sel)); }
        catch { return []; }
    }

    function rect(el) {
        if (!el || !el.getBoundingClientRect) return null;
        const r = el.getBoundingClientRect();
        return { top: r.top, left: r.left, width: r.width, height: r.height };
    }

    function isVisible(el) {
        if (!el) return false;
        const s = getComputedStyle(el);
        if (s.display === "none" || s.visibility === "hidden" || s.opacity === "0") return false;
        const r = el.getBoundingClientRect();
        return r.width > 0 && r.height > 0;
    }

    function serialize(el) {
        return {
            tag: el.tagName.toLowerCase(),
            id: el.id || null,
            classes: [...el.classList],
            text: (el.innerText || "").trim().slice(0, 200),
            attrs: Object.fromEntries([...el.attributes].map(a => [a.name, a.value])),
            rect: rect(el),
            html: el.outerHTML
        };
    }

    function findFormRoots() {
        const roots = new Set();

        qsAll(document, "form").forEach(f => roots.add(f));

        // form-like containers (SPA, JS-only)
        qsAll(document, "div,section").forEach(el => {
            const inputs = qsAll(el, "input,select,textarea");
            const clicks = qsAll(el, "button,a,[role=button],[onclick]");
            if (inputs.length >= 1 && clicks.length >= 1) roots.add(el);
        });

        return [...roots];
    }

    function expandContainer(el, depth = 3) {
        const set = new Set([el]);
        let cur = el;

        // upward
        for (let i = 0; i < depth && cur.parentElement; i++) {
            cur = cur.parentElement;
            set.add(cur);
        }

        // siblings
        if (el.parentElement) {
            [...el.parentElement.children].forEach(c => set.add(c));
        }

        return [...set];
    }

    function collectCandidates(container) {
        const selectors = [
            "button",
            "input",
            "a",
            "[role=button]",
            "[onclick]"
        ];

        const found = new Set();

        selectors.forEach(sel => {
            qsAll(container, sel).forEach(el => {
                if (isVisible(el)) found.add(el);
            });
        });

        return [...found];
    }

    function collectInputs(container) {
        return qsAll(container, "input,select,textarea")
            .filter(isVisible)
            .map(serialize);
    }

    function analyzeRoot(root) {
        const containers = expandContainer(root, 4);

        let inputs = [];
        let actions = [];

        containers.forEach(c => {
            collectInputs(c).forEach(i => inputs.push(i));
            collectCandidates(c).forEach(a => actions.push(serialize(a)));
        });

        return {
            root: serialize(root),
            inputs,
            action_candidates: actions
        };
    }

    // MAIN
    const result = {
        url: location.href,
        timestamp: Date.now(),
        forms: findFormRoots().map(analyzeRoot)
    };

    window.__FORM_INTERACTION_DATA__ = result;
})();
