(() => {
    const discoveredRoutes = new Set();
    const discoveredURLs = new Set();

    const normalize = (url) => {
        try {
            return new URL(url, location.origin).href;
        } catch {
            return null;
        }
    };

    const record = (url) => {
        const n = normalize(url);
        if (n) discoveredRoutes.add(n);
    };

    // history API hooks
    const _pushState = history.pushState;
    history.pushState = function (state, title, url) {
        if (url) record(url);
        return _pushState.apply(this, arguments);
    };

    const _replaceState = history.replaceState;
    history.replaceState = function (state, title, url) {
        if (url) record(url);
        return _replaceState.apply(this, arguments);
    };

    // hash routing
    window.addEventListener("hashchange", () => {
        record(location.hash);
    });

    // location assignment hook
    const loc = window.location;
    ["assign", "replace"].forEach((fn) => {
        const original = loc[fn];
        loc[fn] = function (url) {
            record(url);
            return original.call(this, url);
        };
    });

    // expose safely
    Object.defineProperty(window, "__DISCOVERED_ROUTES__", {
        value: discoveredRoutes,
        writable: false,
    });

    Object.defineProperty(window, "__DISCOVERED_URLS__", {
        value: discoveredURLs,
        writable: false,
    });
})();
