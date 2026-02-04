/**
 * fill_form_from_scan.js
 * Form filler that works with scan_forms.js data structure.
 * 
 * Takes form data from scan_forms.js output and fills the actual form on the webpage.
 * Supports flexible field matching and framework-compatible filling.
 * 
 * Usage:
 *   Option 1: Pass full scan_forms.js JSON output (with "forms" array)
 *             - Update "value" fields in the JSON with actual values
 *             - Pass entire JSON to script
 *             - Script will extract fields with non-empty "value" and fill them
 *   
 *   Option 2: Pass single form object (with "fields" array)
 *   
 *   Option 3: Pass simple key-value mapping
 * 
 * Example with full scan_forms.js output:
 *   const formData = {
 *     formCount: 1,
 *     forms: [{
 *       fields: [
 *         { id: "email", name: "email", value: "user@example.com" },
 *         { id: "password", name: "password", value: "password123" }
 *       ]
 *     }]
 *   };
 *   fillFormFromScan(formData, { autoSubmit: true, formIndex: 0 });
 * 
 * @param {Object|Object[]} formData - Form data structure from scan_forms.js or simple field values
 * @param {Object} options - Options: { autoSubmit: boolean, formIndex: number }
 * @returns {Object} Results with filled fields, missing fields, errors, and submit result
 */
((formData, options = {}) => {
    const results = {
        filled: [],
        missing: [],
        errors: [],
        submitResult: null
    };

    const config = {
        autoSubmit: options.autoSubmit || false,
        formIndex: options.formIndex !== undefined ? options.formIndex : 0
    };

    /**
     * Normalize input data to a consistent structure
     * Handles multiple input formats:
     * 1. Full scan_forms.js output (with forms array)
     * 2. Single form object (with fields array)
     * 3. Simple key-value mapping
     */
    const normalizeFormData = (data) => {
        // Case 1: Full scan_forms.js output structure with "forms" array
        if (data && data.forms && Array.isArray(data.forms)) {
            const formIndex = config.formIndex;
            if (formIndex >= 0 && formIndex < data.forms.length) {
                const selectedForm = data.forms[formIndex];
                // Extract fields that have a value set (non-empty)
                const fieldsWithValues = (selectedForm.fields || []).filter(field => {
                    // Skip buttons unless they're submit buttons (we handle submit separately)
                    if (field.tag === 'button' && field.type !== 'submit') {
                        return false;
                    }
                    // Only include fields with non-empty values
                    return field.value !== undefined && 
                           field.value !== null && 
                           field.value !== '';
                });
                return { fields: fieldsWithValues };
            } else {
                return { fields: [] };
            }
        }
        
        // Case 2: Single form object with fields array (scan_forms.js form structure)
        if (data && data.fields && Array.isArray(data.fields)) {
            // Filter to only fields with values
            const fieldsWithValues = data.fields.filter(field => {
                if (field.tag === 'button' && field.type !== 'submit') {
                    return false;
                }
                return field.value !== undefined && 
                       field.value !== null && 
                       field.value !== '';
            });
            return { fields: fieldsWithValues };
        }
        
        // Case 3: Simple object with key-value pairs, convert to fields array
        if (data && !Array.isArray(data) && typeof data === 'object') {
            const fields = [];
            for (const [key, value] of Object.entries(data)) {
                // Skip if value is empty
                if (value === undefined || value === null || value === '') {
                    continue;
                }
                fields.push({
                    identifier: key,
                    value: value
                });
            }
            return { fields };
        }
        
        // Case 4: Array of field objects
        if (Array.isArray(data)) {
            const fieldsWithValues = data.filter(field => {
                if (field.tag === 'button' && field.type !== 'submit') {
                    return false;
                }
                return field.value !== undefined && 
                       field.value !== null && 
                       field.value !== '';
            });
            return { fields: fieldsWithValues };
        }
        
        return { fields: [] };
    };

    /**
     * Find field element using multiple strategies
     * Priority: id → name → label (fuzzy) → position
     */
    const findFieldElement = (fieldInfo) => {
        let element = null;
        let matchedBy = null;

        // Strategy 1: Match by ID (most reliable)
        if (fieldInfo.id) {
            element = document.getElementById(fieldInfo.id);
            if (element) {
                matchedBy = 'id';
                return { element, matchedBy };
            }
        }

        // Strategy 2: Match by name attribute
        if (fieldInfo.name) {
            element = document.querySelector(`[name="${fieldInfo.name}"]`);
            if (element) {
                matchedBy = 'name';
                return { element, matchedBy };
            }
        }

        // Strategy 3: Match by identifier (if provided as simple key-value)
        if (fieldInfo.identifier) {
            // Try as ID first
            element = document.getElementById(fieldInfo.identifier);
            if (element) {
                matchedBy = 'identifier_as_id';
                return { element, matchedBy };
            }
            
            // Try as name
            element = document.querySelector(`[name="${fieldInfo.identifier}"]`);
            if (element) {
                matchedBy = 'identifier_as_name';
                return { element, matchedBy };
            }
        }

        // Strategy 4: Match by label text (fuzzy)
        if (fieldInfo.label) {
            try {
                const labels = Array.from(document.querySelectorAll('label'));
                const targetLabel = labels.find(l => {
                    const labelText = (l.innerText || l.textContent || '').trim().toLowerCase();
                    const searchText = fieldInfo.label.toLowerCase().replace(/[*\s]/g, '');
                    return labelText.includes(searchText) || searchText.includes(labelText);
                });
                
                if (targetLabel) {
                    // Try to get associated control
                    if (targetLabel.control) {
                        element = targetLabel.control;
                        matchedBy = 'label_control';
                    } else if (targetLabel.getAttribute('for')) {
                        element = document.getElementById(targetLabel.getAttribute('for'));
                        matchedBy = 'label_for';
                    } else {
                        // Find input/select/textarea within label
                        element = targetLabel.querySelector('input, select, textarea');
                        matchedBy = 'label_nested';
                    }
                    
                    if (element) {
                        return { element, matchedBy };
                    }
                }
            } catch (e) {
                // Continue to next strategy
            }
        }

        // Strategy 5: Match by type and position (last resort)
        if (fieldInfo.type && fieldInfo.tag) {
            const candidates = Array.from(document.querySelectorAll(`${fieldInfo.tag}[type="${fieldInfo.type}"]`));
            if (candidates.length > 0 && fieldInfo.index !== undefined) {
                element = candidates[fieldInfo.index] || candidates[0];
                matchedBy = 'type_position';
                return { element, matchedBy };
            }
        }

        return { element: null, matchedBy: null };
    };

    /**
     * Fill a single field with value
     */
    const fillField = (fieldInfo) => {
        try {
            const { element, matchedBy } = findFieldElement(fieldInfo);
            
            if (!element) {
                const identifier = fieldInfo.id || fieldInfo.name || fieldInfo.identifier || fieldInfo.label || 'unknown';
                results.missing.push(identifier);
                return false;
            }

            // Skip if field is disabled or readonly (unless explicitly allowed)
            if (element.disabled && !options.allowDisabled) {
                results.errors.push({
                    field: fieldInfo.id || fieldInfo.name || 'unknown',
                    error: 'Field is disabled',
                    matchedBy
                });
                return false;
            }

            if (element.readOnly && !options.allowReadonly) {
                results.errors.push({
                    field: fieldInfo.id || fieldInfo.name || 'unknown',
                    error: 'Field is readonly',
                    matchedBy
                });
                return false;
            }

            const tagName = element.tagName.toUpperCase();
            const inputType = element.type ? element.type.toLowerCase() : '';
            const value = fieldInfo.value;

            // Focus the element first
            try {
                element.focus();
            } catch (e) {
                // Some elements might not be focusable, continue anyway
            }

            // Get native setters to bypass framework restrictions
            const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype, "value"
            )?.set;
            const nativeTextAreaValueSetter = Object.getOwnPropertyDescriptor(
                window.HTMLTextAreaElement.prototype, "value"
            )?.set;
            const nativeSelectValueSetter = Object.getOwnPropertyDescriptor(
                window.HTMLSelectElement.prototype, "value"
            )?.set;

            // Handle different field types
            if (tagName === 'INPUT') {
                if (inputType === 'checkbox') {
                    // For checkboxes, value should be boolean or 'true'/'false' string
                    const shouldCheck = value === true || value === 'true' || value === 'checked';
                    element.checked = shouldCheck;
                } else if (inputType === 'radio') {
                    // For radio buttons, check if this is the right option
                    if (value === element.value || value === true || value === 'true') {
                        element.checked = true;
                    }
                } else if (inputType === 'file') {
                    // File inputs require File API - skip for now
                    results.errors.push({
                        field: fieldInfo.id || fieldInfo.name || 'unknown',
                        error: 'File inputs require File API - not supported',
                        matchedBy
                    });
                    return false;
                } else {
                    // Text, email, password, number, date, etc.
                    if (nativeInputValueSetter) {
                        nativeInputValueSetter.call(element, value);
                    } else {
                        element.value = value;
                    }
                }
            } else if (tagName === 'TEXTAREA') {
                if (nativeTextAreaValueSetter) {
                    nativeTextAreaValueSetter.call(element, value);
                } else {
                    element.value = value;
                }
            } else if (tagName === 'SELECT') {
                // Try to set value directly first
                try {
                    if (nativeSelectValueSetter) {
                        nativeSelectValueSetter.call(element, value);
                    } else {
                        element.value = value;
                    }
                    
                    // Verify the value was set (in case value doesn't match any option)
                    if (element.value !== value) {
                        // Try to find option by text content
                        const options = Array.from(element.options);
                        const matchingOption = options.find(opt => 
                            opt.value === value || 
                            opt.text.toLowerCase().includes(String(value).toLowerCase())
                        );
                        if (matchingOption) {
                            element.selectedIndex = matchingOption.index;
                        } else {
                            throw new Error(`Option value "${value}" not found in select`);
                        }
                    }
                } catch (e) {
                    results.errors.push({
                        field: fieldInfo.id || fieldInfo.name || 'unknown',
                        error: `Failed to set select value: ${e.message}`,
                        matchedBy
                    });
                    return false;
                }
            } else {
                // Fallback for other element types
                element.value = value;
            }

            // Dispatch events to notify frameworks (React, Vue, Angular, etc.)
            try {
                // Create and dispatch input event
                const inputEvent = new Event('input', { bubbles: true, cancelable: true });
                element.dispatchEvent(inputEvent);

                // Create and dispatch change event
                const changeEvent = new Event('change', { bubbles: true, cancelable: true });
                element.dispatchEvent(changeEvent);

                // For React compatibility, also dispatch React's synthetic events
                if (window.React) {
                    const reactEvent = new Event('input', { bubbles: true });
                    Object.defineProperty(reactEvent, 'target', { value: element, enumerable: true });
                    element.dispatchEvent(reactEvent);
                }

                // Blur the element
                element.blur();
            } catch (e) {
                // Event dispatch might fail in some contexts, but value is already set
            }

            // Record successful fill
            const identifier = fieldInfo.id || fieldInfo.name || fieldInfo.identifier || fieldInfo.label || 'unknown';
            results.filled.push({
                fieldId: identifier,
                matchedBy: matchedBy,
                value: value,
                elementType: tagName,
                inputType: inputType
            });

            return true;
        } catch (e) {
            const identifier = fieldInfo.id || fieldInfo.name || fieldInfo.identifier || fieldInfo.label || 'unknown';
            results.errors.push({
                field: identifier,
                error: e.message,
                stack: e.stack
            });
            return false;
        }
    };

    /**
     * Find and click submit button
     */
    const submitForm = () => {
        try {
            // Strategy 1: Find explicit submit button
            let submitBtn = document.querySelector('button[type="submit"], input[type="submit"]');
            if (submitBtn) {
                submitBtn.click();
                return { success: true, method: 'explicit_submit', button: 'submit' };
            }

            // Strategy 2: Find button with submit-like text
            const buttons = Array.from(document.querySelectorAll('button, input[type="button"]'));
            const submitKeywords = ['submit', 'log', 'sign', 'save', 'send', 'post', 'enter'];
            const actionBtn = buttons.find(b => {
                const text = ((b.innerText || b.textContent || b.value || '') + '').toLowerCase();
                return submitKeywords.some(keyword => text.includes(keyword));
            });

            if (actionBtn) {
                actionBtn.click();
                return { 
                    success: true, 
                    method: 'text_match', 
                    button: actionBtn.innerText || actionBtn.value || 'unknown' 
                };
            }

            // Strategy 3: Find form and submit it programmatically
            const forms = document.querySelectorAll('form');
            if (forms.length > config.formIndex) {
                const form = forms[config.formIndex];
                try {
                    form.requestSubmit(); // Modern way
                    return { success: true, method: 'requestSubmit', button: null };
                } catch (e) {
                    try {
                        form.submit(); // Fallback (doesn't trigger submit event)
                        return { success: true, method: 'form_submit', button: null };
                    } catch (e2) {
                        return { success: false, method: 'none', error: e2.message };
                    }
                }
            }

            return { success: false, method: 'none', error: 'No submit button or form found' };
        } catch (e) {
            return { success: false, method: 'none', error: e.message };
        }
    };

    // Main execution
    try {
        const normalizedData = normalizeFormData(formData);
        
        if (!normalizedData.fields || normalizedData.fields.length === 0) {
            results.errors.push({
                field: 'general',
                error: 'No fields provided in form data'
            });
            return results;
        }

        // Fill all fields (they're already filtered to have values in normalizeFormData)
        normalizedData.fields.forEach(fieldInfo => {
            fillField(fieldInfo);
        });

        // Submit form if requested
        if (config.autoSubmit) {
            const submitResult = submitForm();
            results.submitResult = submitResult.success ? 'clicked' : 'not_found';
            if (!submitResult.success && submitResult.error) {
                results.errors.push({
                    field: 'submit',
                    error: submitResult.error
                });
            }
        } else {
            results.submitResult = 'skipped';
        }

        return results;
    } catch (e) {
        results.errors.push({
            field: 'general',
            error: e.message,
            stack: e.stack
        });
        return results;
    }
})(arguments[0], arguments[1]);
