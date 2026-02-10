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
        const id = el.getAttribute("id");
        if (id) return `#${CSS.escape(id)}`;

        const name = el.getAttribute("name");
        if (name) return `${el.tagName.toLowerCase()}[name="${CSS.escape(name)}"]`;

        // Prioritize common semantic classes for buttons
        if (el.tagName === "BUTTON") {
            if (el.classList.contains("btn-submit")) return "button.btn-submit";
            if (el.classList.contains("submit")) return "button.submit";
        }

        const classes = [...el.classList].filter(c => !c.startsWith("sh-")).map(c => `.${CSS.escape(c)}`).join("");
        if (classes) {
            // If too many classes, just take the first few or relevant ones to avoid massive selectors
            const classArray = [...el.classList].filter(c => !c.startsWith("sh-"));
            if (classArray.length > 3) {
                return `${el.tagName.toLowerCase()}.${CSS.escape(classArray[0])}.${CSS.escape(classArray[1])}`;
            }
            return `${el.tagName.toLowerCase()}${classes}`;
        }

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
                    id: el.getAttribute("id") || null,
                    name: el.getAttribute("name") || null,
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
            id: form.getAttribute("id") || null,
            name: form.getAttribute("name") || null,
            action: form.getAttribute("action") || null,
            method: (form.getAttribute("method") || "GET").toUpperCase(),
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
            id: c.getAttribute("id") || null,
            name: c.getAttribute("name") || null,
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
