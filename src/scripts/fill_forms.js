async (payload) => {
    if (!window.__FORMS_STATE__) {
        return { status: "error", error: "Forms state not initialized. scan_forms.js must run first." };
    }

    const sleep = ms => new Promise(r => setTimeout(r, ms));
    const dispatch = (el, type) => el.dispatchEvent(new Event(type, { bubbles: true }));

    const click = el => {
        el.scrollIntoView({ block: "center", behavior: "smooth" });
        ["mousedown", "mouseup", "click"].forEach(t =>
            el.dispatchEvent(new MouseEvent(t, { bubbles: true }))
        );
        el.focus();
    };

    const type = async (el, value) => {
        click(el);

        // React/Angular hack: trigger built-in setter to ensure state change is detected
        const nativeInputSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
        const nativeTextAreaSetter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value").set;

        const setValue = (val) => {
            if (el.tagName === "INPUT" && nativeInputSetter) {
                nativeInputSetter.call(el, val);
            } else if (el.tagName === "TEXTAREA" && nativeTextAreaSetter) {
                nativeTextAreaSetter.call(el, val);
            } else {
                el.value = val;
            }
            dispatch(el, "input");
            dispatch(el, "change"); // Some frameworks listen on change
        };

        // Clear first
        setValue("");
        await sleep(20);

        // Type characters
        let currentVal = "";
        for (const ch of String(value)) {
            currentVal += ch;
            // React state updates often require setting the FULL value incrementally
            // equivalent to how a user appends text
            setValue(currentVal);
            await sleep(40);
        }

        dispatch(el, "blur");
    };

    const formIndex = payload.formIndex !== undefined ? payload.formIndex : null;
    const customSubmitSelector = payload.submitSelector || null;
    const entries = Object.entries(payload).filter(([k]) => !["formIndex", "submitSelector", "submit"].includes(k));
    const results = [];

    // Step 1: Fill all fields
    for (const [key, value] of entries) {
        let fieldFound = null;
        const formsToSearch = formIndex !== null
            ? window.__FORMS_STATE__.forms.filter(f => f.index === formIndex)
            : window.__FORMS_STATE__.forms;

        for (const form of formsToSearch) {
            const match = form.fields.find(f => f.id === key || f.name === key || f.selector === key);
            if (match) {
                fieldFound = match;
                break;
            }
        }

        if (!fieldFound || !fieldFound.selector) {
            console.warn(`Field with key "${key}" not found in ${formIndex !== null ? `form ${formIndex}` : "any form"}.`);
            results.push({ key, status: "not_found" });
            continue;
        }

        const el = document.querySelector(fieldFound.selector);
        if (!el || el.disabled || el.readOnly) {
            results.push({ key, status: "blocked_or_missing" });
            continue;
        }

        console.log(`Filling ${key} with ${value}`);
        fieldFound.value = value;

        if (fieldFound.tag === "input") {
            if (fieldFound.type === "checkbox" || fieldFound.type === "radio") {
                el.checked = Boolean(value);
                dispatch(el, "change");
            } else {
                await type(el, value);
            }
        } else if (fieldFound.tag === "textarea") {
            await type(el, value);
        } else if (fieldFound.tag === "select") {
            click(el);
            const opt = [...el.options].find(
                o => o.value === String(value) || o.text === String(value)
            );
            if (opt) {
                el.value = opt.value;
                dispatch(el, "change");
            }
        }
        results.push({ key, status: "filled" });
    }

    // Step 2: Handle submission
    if (payload.submit) {
        let submitBtn = null;

        // Priority 1: Custom selector from payload
        if (customSubmitSelector) {
            const btn = document.querySelector(customSubmitSelector);
            if (btn) {
                submitBtn = btn;
            }
        }

        // Priority 2: Fallback to scanned forms state
        if (!submitBtn) {
            const formsToSearch = formIndex !== null
                ? window.__FORMS_STATE__.forms.filter(f => f.index === formIndex)
                : window.__FORMS_STATE__.forms;

            for (const form of formsToSearch) {
                if (form.submitSelector) {
                    const btn = document.querySelector(form.submitSelector);
                    if (btn) {
                        submitBtn = btn;
                        break;
                    }
                }
            }
        }

        if (submitBtn) {
            console.log("Submitting form...");
            click(submitBtn);
            await sleep(500);
            results.push({ key: "submit", status: "clicked" });
        } else {
            results.push({ key: "submit", status: "button_not_found" });
        }
    }

    return {
        status: "success",
        details: results,
        state: window.__FORMS_STATE__
    };
};
