/**
 * scan_forms.js
 * A robust, industrial-strength form scanner for QA automation.
 * Features:
 * - Shadow DOM traversal
 * - Label association (explicit, implicit, ARIA, and proximity)
 * - HTML5 'form' attribute support (fields outside <form> tags)
 * - Form-like container detection (for JS-driven forms without <form> tags)
 * - Computed visibility and positioning
 * - Detection of iframes and cross-origin boundaries
 * - Full HTML capture
 */
(() => {
    try {
        const results = [];
        const seenFields = new Set();
        const seenForms = new Set();

        /**
         * Recursively finds all elements matching a selector, even inside Shadow DOM.
         */
        const findDeep = (root, selector) => {
            let elements = Array.from(root.querySelectorAll(selector));
            const all = root.querySelectorAll('*');
            for (const el of all) {
                if (el.shadowRoot) {
                    elements = elements.concat(findDeep(el.shadowRoot, selector));
                }
            }
            return elements;
        };

        /**
         * Determines the label for an element using various heuristics.
         */
        const extractLabel = (el) => {
            // 1. Explicit <label for="...">
            if (el.id) {
                const labelFor = document.querySelector(`label[for="${el.id}"]`);
                if (labelFor) return labelFor.innerText.trim();
            }

            // 2. Parent <label>
            const parentLabel = el.closest('label');
            if (parentLabel) return parentLabel.innerText.trim();

            // 3. ARIA attributes
            const ariaLabel = el.getAttribute('aria-label');
            if (ariaLabel) return ariaLabel.trim();

            const ariaLabelledBy = el.getAttribute('aria-labelledby');
            if (ariaLabelledBy) {
                const labelEl = document.getElementById(ariaLabelledBy);
                if (labelEl) return labelEl.innerText.trim();
            }

            // 4. Proximity - Check preceding siblings (commonly used in modern frameworks)
            let prev = el.previousElementSibling;
            while (prev) {
                if (['LABEL', 'SPAN', 'DIV', 'H3', 'H4', 'P'].includes(prev.tagName)) {
                    const text = prev.innerText.trim();
                    if (text && text.length < 100) return text;
                    if (text) break; // Found a large block of text, stop
                }
                prev = prev.previousElementSibling;
            }

            // 5. Placeholder
            if (el.placeholder) return `(Placeholder) ${el.placeholder}`;

            // 6. Title
            if (el.title) return `(Title) ${el.title}`;

            // 7. Value (for buttons)
            if (el.tagName === 'INPUT' && (el.type === 'button' || el.type === 'submit')) {
                return el.value;
            }

            return null;
        };

        const getAriaAttributes = (el) => {
            const aria = {};
            for (const attr of el.attributes) {
                if (attr.name.startsWith('aria-')) {
                    aria[attr.name] = attr.value;
                }
            }
            return aria;
        };

        const isVisible = (el) => {
            if (!el) return false;
            const style = window.getComputedStyle(el);
            return (
                style.display !== 'none' &&
                style.visibility !== 'hidden' &&
                style.opacity !== '0' &&
                el.offsetWidth > 0 &&
                el.offsetHeight > 0
            );
        };

        const formatField = (el) => {
            const tag = el.tagName.toLowerCase();
            const rect = el.getBoundingClientRect();
            const fieldData = {
                tag,
                type: el.type || (tag === 'button' ? 'button' : tag),
                name: el.name || null,
                id: el.id || null,
                label: extractLabel(el),
                value: el.value || '',
                placeholder: el.placeholder || null,
                required: el.required || false,
                disabled: el.disabled || false,
                readOnly: el.readOnly || false,
                isVisible: isVisible(el),
                rect: {
                    x: rect.x + window.scrollX,
                    y: rect.y + window.scrollY,
                    width: rect.width,
                    height: rect.height
                },
                aria: getAriaAttributes(el),
                outerHTML: el.outerHTML
            };

            if (tag === 'select') {
                fieldData.options = Array.from(el.options).map(o => ({
                    text: o.text,
                    value: o.value,
                    selected: o.selected
                }));
            }

            if (tag === 'input' && (el.type === 'checkbox' || el.type === 'radio')) {
                fieldData.checked = el.checked;
            }

            return fieldData;
        };

        // --- STEP 1: Process Explicit <form> Tags ---
        const forms = findDeep(document, 'form');
        forms.forEach((formEl, index) => {
            seenForms.add(formEl);
            const fields = [];

            // Collect fields associated with this form (physically or via 'form' attribute)
            const allPotentiallyAssociated = findDeep(document, 'input, select, textarea, button');
            allPotentiallyAssociated.forEach(f => {
                // The .form property is natively supported in browsers to find the owner form
                if (f.form === formEl) {
                    fields.push(formatField(f));
                    seenFields.add(f);
                }
            });

            results.push({
                type: 'form',
                index,
                id: formEl.id || null,
                name: formEl.name || null,
                action: formEl.getAttribute('action') || null,
                method: (formEl.getAttribute('method') || 'GET').toUpperCase(),
                outerHTML: formEl.outerHTML,
                fields,
                fieldCount: fields.length
            });
        });

        // --- STEP 2: Process "Form-Like" Containers (Orphaned Fields) ---
        const allFields = findDeep(document, 'input, select, textarea, button');
        const orphanedFields = allFields.filter(f => !seenFields.has(f));

        if (orphanedFields.length > 0) {
            // Group orphaned fields by their closest meaningful container
            const containerMap = new Map();
            orphanedFields.forEach(f => {
                // Find a logical container (div, section, etc.) or a role-based container
                let container = f.closest('div, section, article, [role="form"], [role="dialog"], [role="group"]');

                // If no container found or container is too generic, use parent
                if (!container || container === document.body) {
                    container = f.parentElement || document.body;
                }

                if (!containerMap.has(container)) {
                    containerMap.set(container, []);
                }
                containerMap.get(container).push(f);
            });

            // For each container, if it has 2+ fields OR a submit-like button, treat as a form
            containerMap.forEach((fieldsInContainer, container) => {
                const hasInput = fieldsInContainer.some(f => ['INPUT', 'TEXTAREA', 'SELECT'].includes(f.tagName));
                const hasSubmit = fieldsInContainer.some(f =>
                    (f.tagName === 'BUTTON' && (f.type === 'submit' || !f.type)) ||
                    (f.tagName === 'INPUT' && f.type === 'submit')
                );

                if (hasInput && (fieldsInContainer.length >= 2 || hasSubmit)) {
                    const fields = fieldsInContainer.map(formatField);
                    results.push({
                        type: 'form-like',
                        index: results.length,
                        id: container.id || null,
                        tag: container.tagName.toLowerCase(),
                        role: container.getAttribute('role') || null,
                        outerHTML: container.outerHTML,
                        fields,
                        fieldCount: fields.length
                    });
                }
            });
        }

        // --- STEP 3: Check for iframes (Cross-context forms) ---
        const iframes = findDeep(document, 'iframe');
        const iframeInfo = iframes.map(frame => {
            let details = {
                tag: 'iframe',
                id: frame.id || null,
                name: frame.name || null,
                src: frame.src || null,
                isVisible: isVisible(frame),
            };

            try {
                // If we can access contentDocument, it's same-origin
                if (frame.contentDocument) {
                    details.isAccessible = true;
                    // We don't recurse here because the script is usually executed per-frame by the driver
                } else {
                    details.isAccessible = false;
                    details.reason = 'Cross-origin block';
                }
            } catch (e) {
                details.isAccessible = false;
                details.reason = 'Security Error';
            }
            return details;
        });

        return {
            formCount: results.length,
            forms: results,
            iframes: iframeInfo,
            metadata: {
                url: window.location.href,
                timestamp: new Date().toISOString(),
                viewport: {
                    width: window.innerWidth,
                    height: window.innerHeight
                }
            }
        };

    } catch (e) {
        return {
            error: true,
            message: e.message,
            stack: e.stack,
            partialResults: results
        };
    }
})();
