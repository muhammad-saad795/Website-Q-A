/**
 * fill_forms.js
 * Consumes scanned form JSON and fills fields reliably.
 */
((payload) => {
    if (!payload || !payload.forms) {
        throw new Error("Invalid form payload");
    }

    const dispatchEvents = (el) => {
        el.dispatchEvent(new Event("focus", { bubbles: true }));
        el.dispatchEvent(new Event("input", { bubbles: true }));
        el.dispatchEvent(new Event("change", { bubbles: true }));
        el.dispatchEvent(new Event("blur", { bubbles: true }));
    };

    const findField = (field) => {
        if (field.id) {
            const el = document.getElementById(field.id);
            if (el) return el;
        }

        if (field.name) {
            const el = document.querySelector(`[name="${CSS.escape(field.name)}"]`);
            if (el) return el;
        }

        if (field.placeholder) {
            const el = Array.from(document.querySelectorAll("input, textarea"))
                .find(e => e.placeholder === field.placeholder);
            if (el) return el;
        }

        if (field.aria) {
            for (const [key, val] of Object.entries(field.aria)) {
                const el = document.querySelector(`[${key}="${CSS.escape(val)}"]`);
                if (el) return el;
            }
        }

        // LAST RESORT: positional match
        if (field.rect) {
            const candidates = Array.from(document.querySelectorAll(field.tag));
            return candidates.find(el => {
                const r = el.getBoundingClientRect();
                return (
                    Math.abs(r.x - field.rect.x) < 5 &&
                    Math.abs(r.y - field.rect.y) < 5
                );
            });
        }

        return null;
    };

    const fillField = (el, field) => {
        if (field.disabled || field.readOnly) return;

        if (field.tag === "input") {
            if (field.type === "checkbox" || field.type === "radio") {
                el.checked = Boolean(field.value);
                dispatchEvents(el);
                return;
            }

            el.value = field.value ?? "";
            dispatchEvents(el);
            return;
        }

        if (field.tag === "textarea") {
            el.value = field.value ?? "";
            dispatchEvents(el);
            return;
        }

        if (field.tag === "select") {
            const option = Array.from(el.options)
                .find(o => o.value === field.value || o.text === field.value);
            if (option) {
                el.value = option.value;
                dispatchEvents(el);
            }
            return;
        }
    };

    payload.forms.forEach(form => {
        form.fields.forEach(field => {
            if (!field.value) return;

            const el = findField(field);
            if (!el) return;

            fillField(el, field);
        });

        // Auto-submit if submit button exists
        const submitBtn = form.fields
            .map(f => findField(f))
            .find(el => el && el.tagName === "BUTTON" && el.type === "submit");

        if (submitBtn) {
            submitBtn.click();
        }
    });

    return { status: "filled" };
});
