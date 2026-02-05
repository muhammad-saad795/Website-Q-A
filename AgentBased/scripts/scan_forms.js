(() => {
    const formsState = {
        url: location.href,
        forms: []
    };

    const isVisible = el => {
        const s = getComputedStyle(el);
        return s.display !== "none" && s.visibility !== "hidden" &&
            el.offsetWidth > 0 && el.offsetHeight > 0;
    };

    const getLabel = el => {
        if (el.tagName === "BUTTON" || el.tagName === "A") {
            return el.innerText.trim() || el.title || el.ariaLabel || null;
        }
        if (el.id) {
            const l = document.querySelector(`label[for="${el.id}"]`);
            if (l) return l.innerText.trim();
        }
        const parent = el.closest("label");
        if (parent) return parent.innerText.trim();
        return el.placeholder || el.title || el.ariaLabel || null;
    };

    const buildSelector = el => {
        if (el.id) return `#${CSS.escape(el.id)}`;
        if (el.name) return `${el.tagName.toLowerCase()}[name="${CSS.escape(el.name)}"]`;

        const classes = [...el.classList].filter(c => !c.startsWith("sh-")).map(c => `.${CSS.escape(c)}`).join("");
        if (classes) return `${el.tagName.toLowerCase()}${classes}`;

        if (el.type) return `${el.tagName.toLowerCase()}[type="${CSS.escape(el.type)}"]`;

        return el.tagName.toLowerCase();
    };

    const collectFields = root =>
        [...root.querySelectorAll("input,textarea,select,button")]
            .filter(isVisible)
            .map(el => {
                const field = {
                    tag: el.tagName.toLowerCase(),
                    type: el.type || null,
                    id: el.id || null,
                    name: el.name || null,
                    label: getLabel(el),
                    placeholder: el.placeholder || null,
                    value: "",
                    checked: el.checked ?? null,
                    disabled: el.disabled,
                    readOnly: el.readOnly,
                    isVisible: true,
                    selector: buildSelector(el)
                };

                if (el.tagName === "SELECT") {
                    field.options = [...el.options].map(o => ({
                        value: o.value,
                        text: o.text
                    }));
                }

                return field;
            });

    let currentFormIndex = 0;
    // Native forms
    document.querySelectorAll("form").forEach((form, i) => {
        formsState.forms.push({
            index: currentFormIndex++,
            id: form.id || null,
            name: form.name || null,
            action: form.action || null,
            method: (form.method || "GET").toUpperCase(),
            isNativeForm: true,
            submitSelector:
                form.querySelector('[type="submit"]')
                    ? buildSelector(form.querySelector('[type="submit"]'))
                    : null,
            fields: collectFields(form)
        });
    });

    // JS form-like containers
    document.querySelectorAll('[role="form"], .form, .form-group').forEach((c, i) => {
        if (c.querySelector("form") || c.closest("form")) return;

        const fields = collectFields(c);
        if (fields.length < 2) return;

        formsState.forms.push({
            index: currentFormIndex++,
            id: c.id || null,
            name: null,
            action: null,
            method: null,
            isNativeForm: false,
            submitSelector:
                c.querySelector('[type="submit"]')
                    ? buildSelector(c.querySelector('[type="submit"]'))
                    : null,
            fields
        });
    });

    window.__FORMS_STATE__ = formsState;
    return formsState;
})();
