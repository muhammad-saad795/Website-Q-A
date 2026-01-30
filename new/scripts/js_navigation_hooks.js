(() => {
    if (window.__DISCOVERED_JS_URLS__) return;

    window.__DISCOVERED_JS_URLS__ = new Set();

    function record(url) {
        if (!url) return;
        try {
            window.__DISCOVERED_JS_URLS__.add(url.toString());
        } catch { }
    }

    // SPA routing
    const push = history.pushState;
    history.pushState = function (_, __, url) {
        record(url);
        return push.apply(this, arguments);
    };

    const replace = history.replaceState;
    history.replaceState = function (_, __, url) {
        record(url);
        return replace.apply(this, arguments);
    };

    // Programmatic navigation
    const assign = location.assign;
    location.assign = function (url) {
        record(url);
        return assign.call(this, url);
    };

    const open = window.open;
    window.open = function (url) {
        record(url);
        return open.apply(this, arguments);
    };
})();
