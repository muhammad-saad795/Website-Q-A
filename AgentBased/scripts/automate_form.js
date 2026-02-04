/**
 * automate_form.js
 * An intelligent form filler that uses AI-provided data.
 * Usage: Pass a 'formData' object where keys are field IDs or Names.
 */
((formData) => {
    try {
        const results = {
            filled: [],
            missing: [],
            errors: []
        };

        const fillField = (fieldIdOrName, value) => {
            // Try finding by ID first, then Name, then Label text (fuzzy)
            let el = document.getElementById(fieldIdOrName) ||
                document.querySelector(`[name="${fieldIdOrName}"]`);

            if (!el) {
                // Fallback: search for a label that matches the key
                const labels = Array.from(document.querySelectorAll('label'));
                const targetLabel = labels.find(l => l.innerText.toLowerCase().includes(fieldIdOrName.toLowerCase()));
                if (targetLabel && targetLabel.control) {
                    el = targetLabel.control;
                }
            }

            if (el) {
                el.focus();

                // Use Native setters to bypass framework restrictions (e.g. React)
                const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
                const nativeTextAreaValueSetter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value").set;
                const nativeSelectValueSetter = Object.getOwnPropertyDescriptor(window.HTMLSelectElement.prototype, "value").set;

                if (el.tagName === 'INPUT') {
                    nativeInputValueSetter.call(el, value);
                } else if (el.tagName === 'TEXTAREA') {
                    nativeTextAreaValueSetter.call(el, value);
                } else if (el.tagName === 'SELECT') {
                    nativeSelectValueSetter.call(el, value);
                } else {
                    el.value = value;
                }

                // Dispatch events so the website knows data has changed
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
                el.blur();

                results.filled.push(fieldIdOrName);
            } else {
                results.missing.push(fieldIdOrName);
            }
        };

        // 1. Fill all provided data
        for (const [key, value] of Object.entries(formData)) {
            fillField(key, value);
        }

        // 2. Identify and click the submit button
        const findAndClickSubmit = () => {
            // Check for explicit submit buttons first
            const submitBtn = document.querySelector('button[type="submit"], input[type="submit"]');
            if (submitBtn) {
                submitBtn.click();
                return "Clicked explicit submit button";
            }

            // Fallback: look for buttons with "Login", "Submit", "Sign In" text
            const buttons = Array.from(document.querySelectorAll('button, input[type="button"], a.btn'));
            const actionBtn = buttons.find(b => {
                const text = (b.innerText || b.value || "").toLowerCase();
                return text.includes('log') || text.includes('submit') || text.includes('sign') || text.includes('save');
            });

            if (actionBtn) {
                actionBtn.click();
                return `Clicked action button: ${actionBtn.innerText || actionBtn.value}`;
            }

            return "No submit button found";
        };

        results.submission = findAndClickSubmit();
        return results;

    } catch (e) {
        return { error: e.message, stack: e.stack };
    }
})(arguments[0]);
