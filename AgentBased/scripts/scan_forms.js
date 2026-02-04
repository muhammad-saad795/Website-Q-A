/**
 * scan_forms.js
 * A robust form scanner for QA automation.
 * Extracts detailed metadata from forms and form-like containers.
 */
(() => {
    try {
        const results = [];
        const claimedFields = new Set();

        /**
         * Finds the label associated with an input element.
         */
        const extractLabel = (el) => {
            // 1. Label with 'for' attribute
            if (el.id) {
                const labelFor = document.querySelector(`label[for="${el.id}"]`);
                if (labelFor) return labelFor.innerText.trim();
            }

            // 2. Parent label element
            const parentLabel = el.closest('label');
            if (parentLabel) return parentLabel.innerText.trim();

            // 3. aria-label
            const ariaLabel = el.getAttribute('aria-label');
            if (ariaLabel) return ariaLabel.trim();

            // 4. aria-labelledby
            const ariaLabelledBy = el.getAttribute('aria-labelledby');
            if (ariaLabelledBy) {
                const labelEl = document.getElementById(ariaLabelledBy);
                if (labelEl) return labelEl.innerText.trim();
            }

            // 5. Placeholder as fallback
            if (el.placeholder) return `(Placeholder) ${el.placeholder}`;

            // 6. Title attribute
            if (el.title) return `(Title) ${el.title}`;

            return null;
        };

        /**
         * Captures all ARIA attributes on an element.
         */
        const getAriaAttributes = (el) => {
            const aria = {};
            for (const attr of el.attributes) {
                if (attr.name.startsWith('aria-')) {
                    aria[attr.name] = attr.value;
                }
            }
            return aria;
        };

        /**
         * Identifies the primary submit button in a container.
         */
        const identifySubmitButton = (container) => {
            const submitSelectors = [
                'input[type="submit"]',
                'button[type="submit"]',
                'button:not([type])', // Defaults to submit in many browsers
                'input[type="button"][value*="Submit" i]',
                'button:contains("Submit"), button:contains("Login"), button:contains("Register")', // Needs specialized check
            ];

            // Real submit buttons first
            let btn = container.querySelector('input[type="submit"], button[type="submit"]');
            if (btn) return formatButton(btn);

            // Form-like containers or fallback
            const allButtons = container.querySelectorAll('button, input[type="button"]');
            for (const b of allButtons) {
                const text = (b.innerText || b.value || "").toLowerCase();
                if (text.includes('submit') || text.includes('log') || text.includes('sign') || text.includes('save') || text.includes('create')) {
                    return formatButton(b);
                }
            }

            // Take the last button if multiple exist and none matched
            if (allButtons.length > 0) {
                return formatButton(allButtons[allButtons.length - 1]);
            }

            return null;
        };

        const formatButton = (el) => {
            return {
                tag: el.tagName.toLowerCase(),
                type: el.type || (el.tagName === 'BUTTON' ? 'submit' : null),
                id: el.id || null,
                name: el.name || null,
                text: (el.innerText || el.value || "").trim(),
                outerHTML: el.outerHTML
            };
        };

        /**
         * Main field extraction logic.
         */
        const extractFields = (root) => {
            return Array.from(
                root.querySelectorAll("input:not([type='submit']), textarea, select")
            ).map(el => {
                const tag = el.tagName.toLowerCase();
                const type = el.type || tag;
                const id = el.id || null;
                const name = el.name || null;

                // Track claimed fields to avoid duplicates in 'form-like' detection
                claimedFields.add(el);

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
                    name,
                    id,
                    label: extractLabel(el),
                    placeholder: el.placeholder || null,
                    ariaAttributes: getAriaAttributes(el),
                    required: el.required || false,
                    disabled: el.disabled || false,
                    value: el.value || null,
                    isVisible: el.offsetWidth > 0 && el.offsetHeight > 0,
                    options
                };
            });
        };

        // 1. Genuine <form> elements
        document.querySelectorAll("form").forEach((form, index) => {
            const fields = extractFields(form);
            if (!fields.length && !identifySubmitButton(form)) return;

            results.push({
                type: "form",
                index,
                id: form.id || null,
                name: form.name || null,
                action: form.action || null,
                method: (form.method || "GET").toUpperCase(),
                fields,
                submitButton: identifySubmitButton(form),
                outerHTML: form.outerHTML
            });
        });

        // 2. Form-like containers (e.g., login divs not using <form>)
        // Look for common container patterns
        const containers = document.querySelectorAll('div, section, article, [role="form"]');
        containers.forEach(container => {
            // Only process if it contains fields not already claimed by a real <form>
            const innerFields = Array.from(container.querySelectorAll('input, select, textarea'))
                .filter(f => !claimedFields.has(f));

            if (innerFields.length >= 2) {
                const fields = extractFields(container);
                results.push({
                    type: "form-like",
                    index: results.length,
                    id: container.id || null,
                    role: container.getAttribute('role') || null,
                    fields,
                    submitButton: identifySubmitButton(container),
                    outerHTML: container.outerHTML
                });
            }
        });

        return results;
    } catch (e) {
        return { error: e.message, stack: e.stack };
    }
})();
