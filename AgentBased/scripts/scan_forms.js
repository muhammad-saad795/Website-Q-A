/**
 * scan_forms.js
 * Production-ready form scanner for QA automation.
 * Features:
 * - Shadow DOM traversal (optimized)
 * - Same-origin iframe recursion
 * - Label association (explicit, implicit, ARIA, and proximity)
 * - HTML5 'form' attribute support (fields outside <form> tags)
 * - Form-like container detection (for JS-driven forms without <form> tags)
 * - Computed visibility and positioning
 * - Complete HTML capture with fallback serialization
 * - Per-form error handling (continues on failures)
 */
(() => {
    const results = [];
    const errors = [];
    const seenFields = new Set();
    const seenForms = new Set();
    const processedIframes = new Set(); // Track processed iframes to avoid infinite loops

    /**
     * Safely serialize element to HTML string with fallback
     */
    const serializeElement = (el) => {
        try {
            // Try native outerHTML first (fastest and most accurate)
            if (el.outerHTML) {
                return el.outerHTML;
            }
        } catch (e) {
            // Fallback to manual serialization if outerHTML fails
        }

        // Manual serialization fallback
        try {
            const tagName = el.tagName.toLowerCase();
            let html = `<${tagName}`;

            // Add all attributes
            if (el.attributes && el.attributes.length > 0) {
                for (let i = 0; i < el.attributes.length; i++) {
                    const attr = el.attributes[i];
                    const value = attr.value ? `="${attr.value.replace(/"/g, '&quot;')}"` : '';
                    html += ` ${attr.name}${value}`;
                }
            }

            html += '>';

            // Add innerHTML for elements that can have content
            if (['form', 'div', 'section', 'fieldset'].includes(tagName)) {
                html += el.innerHTML || '';
            }

            html += `</${tagName}>`;
            return html;
        } catch (e) {
            return `<${el.tagName.toLowerCase()} [serialization failed]>`;
        }
    };

    /**
     * Optimized Shadow DOM traversal with caching
     */
    const shadowRootCache = new WeakMap();
    
    const findDeep = (root, selector) => {
        let elements = [];
        
        try {
            // Query in current root
            const directElements = root.querySelectorAll(selector);
            elements = Array.from(directElements);
            
            // Find all elements with shadow roots (optimized - single query)
            const allElements = root.querySelectorAll('*');
            const shadowRoots = [];
            
            for (const el of allElements) {
                if (el.shadowRoot) {
                    // Check cache to avoid processing same shadow root twice
                    if (!shadowRootCache.has(el.shadowRoot)) {
                        shadowRootCache.set(el.shadowRoot, true);
                        shadowRoots.push(el.shadowRoot);
                    }
                }
            }
            
            // Recursively process shadow roots
            for (const shadowRoot of shadowRoots) {
                try {
                    elements = elements.concat(findDeep(shadowRoot, selector));
                } catch (e) {
                    // Continue if shadow root access fails
                }
            }
        } catch (e) {
            // Continue if query fails
        }
        
        return elements;
    };

    /**
     * Recursively scan iframes for forms
     */
    const scanIframeForms = (iframe, iframeContext = '') => {
        const iframeId = iframe.id || iframe.name || iframe.src || 'unknown';
        const iframeKey = `${iframeContext}:${iframeId}`;
        
        // Avoid infinite loops and duplicate processing
        if (processedIframes.has(iframeKey)) {
            return [];
        }
        processedIframes.add(iframeKey);
        
        const iframeForms = [];
        
        try {
            let iframeDoc = null;
            
            // Try to access iframe content
            try {
                iframeDoc = iframe.contentDocument || iframe.contentWindow?.document;
            } catch (e) {
                // Cross-origin or security error
                return [];
            }
            
            if (!iframeDoc) {
                return [];
            }
            
            // Scan forms in iframe
            const iframeFormElements = findDeep(iframeDoc, 'form');
            
            iframeFormElements.forEach((formEl, index) => {
                try {
                    // Avoid processing same form twice
                    if (seenForms.has(formEl)) {
                        return;
                    }
                    seenForms.add(formEl);
                    
                    const fields = [];
                    const iframeFields = findDeep(iframeDoc, 'input, select, textarea, button');
                    
                    iframeFields.forEach(f => {
                        try {
                            if (f.form === formEl) {
                                const fieldData = formatField(f);
                                fields.push(fieldData);
                                seenFields.add(f);
                            }
                        } catch (e) {
                            // Continue if field processing fails
                        }
                    });
                    
                    iframeForms.push({
                        type: 'form',
                        index: results.length + iframeForms.length,
                        id: formEl.id || null,
                        name: formEl.name || null,
                        action: formEl.getAttribute('action') || null,
                        method: (formEl.getAttribute('method') || 'GET').toUpperCase(),
                        outerHTML: serializeElement(formEl),
                        fields,
                        fieldCount: fields.length,
                        iframeContext: iframeContext ? `${iframeContext} > ${iframeId}` : iframeId
                    });
                } catch (e) {
                    errors.push({
                        type: 'form_processing_error',
                        context: `iframe: ${iframeId}`,
                        message: e.message,
                        stack: e.stack
                    });
                }
            });
            
            // Recursively scan nested iframes
            const nestedIframes = findDeep(iframeDoc, 'iframe');
            nestedIframes.forEach(nestedIframe => {
                try {
                    const nestedForms = scanIframeForms(nestedIframe, iframeContext ? `${iframeContext} > ${iframeId}` : iframeId);
                    iframeForms.push(...nestedForms);
                } catch (e) {
                    // Continue if nested iframe scan fails
                }
            });
            
        } catch (e) {
            errors.push({
                type: 'iframe_scan_error',
                context: iframeId,
                message: e.message,
                stack: e.stack
            });
        }
        
        return iframeForms;
    };

    /**
     * Determines the label for an element using various heuristics.
     */
    const extractLabel = (el) => {
        try {
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
        } catch (e) {
            return null;
        }
    };

    const getAriaAttributes = (el) => {
        const aria = {};
        try {
            if (el.attributes) {
                for (const attr of el.attributes) {
                    if (attr.name.startsWith('aria-')) {
                        aria[attr.name] = attr.value;
                    }
                }
            }
        } catch (e) {
            // Continue if attribute access fails
        }
        return aria;
    };

    const isVisible = (el) => {
        if (!el) return false;
        try {
            const style = window.getComputedStyle(el);
            return (
                style.display !== 'none' &&
                style.visibility !== 'hidden' &&
                style.opacity !== '0' &&
                el.offsetWidth > 0 &&
                el.offsetHeight > 0
            );
        } catch (e) {
            // If computed style fails, assume visible
            return true;
        }
    };

    const formatField = (el) => {
        try {
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
                outerHTML: serializeElement(el)
            };

            if (tag === 'select') {
                try {
                    fieldData.options = Array.from(el.options).map(o => ({
                        text: o.text,
                        value: o.value,
                        selected: o.selected
                    }));
                } catch (e) {
                    fieldData.options = [];
                }
            }

            if (tag === 'input' && (el.type === 'checkbox' || el.type === 'radio')) {
                fieldData.checked = el.checked;
            }

            return fieldData;
        } catch (e) {
            // Return minimal field data if formatting fails
            return {
                tag: el.tagName?.toLowerCase() || 'unknown',
                type: el.type || 'unknown',
                name: el.name || null,
                id: el.id || null,
                outerHTML: serializeElement(el),
                error: e.message
            };
        }
    };

    try {
        // --- STEP 1: Process Explicit <form> Tags in Main Document ---
        const forms = findDeep(document, 'form');
        forms.forEach((formEl, index) => {
            try {
                // Avoid processing same form twice
                if (seenForms.has(formEl)) {
                    return;
                }
                seenForms.add(formEl);
                
                const fields = [];

                // Collect fields associated with this form (physically or via 'form' attribute)
                const allPotentiallyAssociated = findDeep(document, 'input, select, textarea, button');
                allPotentiallyAssociated.forEach(f => {
                    try {
                        // The .form property is natively supported in browsers to find the owner form
                        if (f.form === formEl) {
                            const fieldData = formatField(f);
                            fields.push(fieldData);
                            seenFields.add(f);
                        }
                    } catch (e) {
                        // Continue if field processing fails
                    }
                });

                results.push({
                    type: 'form',
                    index: results.length,
                    id: formEl.id || null,
                    name: formEl.name || null,
                    action: formEl.getAttribute('action') || null,
                    method: (formEl.getAttribute('method') || 'GET').toUpperCase(),
                    outerHTML: serializeElement(formEl),
                    fields,
                    fieldCount: fields.length,
                    iframeContext: null
                });
            } catch (e) {
                errors.push({
                    type: 'form_processing_error',
                    context: 'main_document',
                    message: e.message,
                    stack: e.stack
                });
            }
        });

        // --- STEP 2: Process Forms in Same-Origin Iframes (Recursive) ---
        const iframes = findDeep(document, 'iframe');
        const iframeInfo = [];
        
        iframes.forEach(frame => {
            try {
                const frameDetails = {
                    tag: 'iframe',
                    id: frame.id || null,
                    name: frame.name || null,
                    src: frame.src || null,
                    isVisible: isVisible(frame),
                };

                try {
                    // Check if iframe is accessible
                    const testDoc = frame.contentDocument || frame.contentWindow?.document;
                    if (testDoc) {
                        frameDetails.isAccessible = true;
                        // Scan forms in this iframe
                        const iframeForms = scanIframeForms(frame);
                        results.push(...iframeForms);
                    } else {
                        frameDetails.isAccessible = false;
                        frameDetails.reason = 'Cross-origin block';
                    }
                } catch (e) {
                    frameDetails.isAccessible = false;
                    frameDetails.reason = 'Security Error';
                }
                
                iframeInfo.push(frameDetails);
            } catch (e) {
                errors.push({
                    type: 'iframe_info_error',
                    message: e.message,
                    stack: e.stack
                });
            }
        });

        // --- STEP 3: Process "Form-Like" Containers (Orphaned Fields) ---
        const allFields = findDeep(document, 'input, select, textarea, button');
        const orphanedFields = allFields.filter(f => !seenFields.has(f));

        if (orphanedFields.length > 0) {
            // Group orphaned fields by their closest meaningful container
            const containerMap = new Map();
            orphanedFields.forEach(f => {
                try {
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
                } catch (e) {
                    // Continue if container finding fails
                }
            });

            // For each container, if it has 2+ fields OR a submit-like button, treat as a form
            containerMap.forEach((fieldsInContainer, container) => {
                try {
                    const hasInput = fieldsInContainer.some(f => ['INPUT', 'TEXTAREA', 'SELECT'].includes(f.tagName));
                    const hasSubmit = fieldsInContainer.some(f =>
                        (f.tagName === 'BUTTON' && (f.type === 'submit' || !f.type)) ||
                        (f.tagName === 'INPUT' && f.type === 'submit')
                    );

                    if (hasInput && (fieldsInContainer.length >= 2 || hasSubmit)) {
                        const fields = fieldsInContainer.map(f => {
                            try {
                                return formatField(f);
                            } catch (e) {
                                return null;
                            }
                        }).filter(Boolean);
                        
                        results.push({
                            type: 'form-like',
                            index: results.length,
                            id: container.id || null,
                            tag: container.tagName.toLowerCase(),
                            role: container.getAttribute('role') || null,
                            outerHTML: serializeElement(container),
                            fields,
                            fieldCount: fields.length,
                            iframeContext: null
                        });
                    }
                } catch (e) {
                    errors.push({
                        type: 'form_like_processing_error',
                        message: e.message,
                        stack: e.stack
                    });
                }
            });
        }

        return {
            formCount: results.length,
            forms: results,
            iframes: iframeInfo,
            errors: errors.length > 0 ? errors : undefined,
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
            partialResults: results,
            errors: errors.length > 0 ? errors : undefined
        };
    }
})();
