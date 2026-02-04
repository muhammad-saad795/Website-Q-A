// form_detector.js
(() => {
    try {
        const results = [];
        const claimedElements = new Set();

        // ---- helpers ----
        const getFieldSignature = (el) => {
            return (
                el.tagName +
                "|" +
                (el.type || "") +
                "|" +
                (el.name || "") +
                "|" +
                (el.id || "")
            );
        };

        const extractFields = (root) => {
            return Array.from(
                root.querySelectorAll("input, textarea, select")
            ).map(el => {
                const tag = el.tagName.toLowerCase();
                const type = el.type || tag;

                let options = [];
                if (tag === "select") {
                    options = Array.from(el.options).map(o => ({
                        value: o.value,
                        text: o.text,
                        selected: o.selected
                    }));
                }

                return {
                    tag,
                    type,
                    name: el.name || null,
                    id: el.id || null,
                    placeholder: el.placeholder || null,
                    required: el.required || false,
                    disabled: el.disabled || false,
                    value: el.value || null,
                    options
                };
            });
        };

        const markClaimed = (fields) => {
            fields.forEach(f => {
                claimedElements.add(
                    `${f.tag}|${f.type}|${f.name}|${f.id}`
                );
            });
        };

        const isUnclaimed = (el) => {
            const sig = getFieldSignature(el);
            return !claimedElements.has(sig);
        };

        // ---- 1️⃣ real <form> elements ----
        document.querySelectorAll("form").forEach((form, index) => {
            const fields = extractFields(form);
            if (!fields.length) return;

            markClaimed(fields);

            results.push({
                type: "form",
                index,
                id: form.id || null,
                name: form.name || null,
                action: form.action || null,
                method: form.method || "GET",
                fields
            });
        });

        // ---- 2️⃣ form-like containers (unclaimed only) ----
        const candidates = Array.from(
            document.querySelectorAll("div, section, article")
        );

        candidates.forEach(container => {
            const fields = Array.from(
                container.querySelectorAll("input, textarea, select")
            )
                .filter(isUnclaimed)
                .map(el => extractFields(el.closest("*"))[0])
                .filter(Boolean);

            if (fields.length < 2) return;

            markClaimed(fields);

            results.push({
                type: "form-like",
                index: results.length,
                id: container.id || null,
                name: container.getAttribute("name") || null,
                action: null,
                method: null,
                fields
            });
        });

        return results;
    } catch (e) {
        console.error("Form detector failed:", e);
        return [];
    }
})();
