// form_detection.js - Production-Grade Form QA System
// Intelligent form discovery with multi-criteria submit button detection

/* ==========================================================================
   UTILITY FUNCTIONS
   ========================================================================== */

/**
 * Recursively get all elements including Shadow DOM
 */
function getAllElements(root = document) {
    let elements = [];
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT, null, false);
    let node = walker.nextNode();
    while (node) {
        elements.push(node);
        if (node.shadowRoot) {
            elements = elements.concat(getAllElements(node.shadowRoot));
        }
        node = walker.nextNode();
    }
    return elements;
}

/**
 * Check if element is visible
 */
function isVisible(el) {
    if (!el) return false;
    const style = window.getComputedStyle(el);
    return style.display !== 'none' &&
        style.visibility !== 'hidden' &&
        style.opacity !== '0' &&
        el.offsetWidth > 0 &&
        el.offsetHeight > 0;
}

/**
 * Generate robust CSS selector for automation
 */
function getSelector(el) {
    if (!el || el.nodeType !== 1) return '';
    if (el.id) return `#${el.id}`;

    // Automation hooks (high priority)
    const testAttrs = ['data-testid', 'data-qa', 'data-cy', 'name', 'aria-label'];
    for (const attr of testAttrs) {
        if (el.hasAttribute(attr)) {
            return `${el.tagName.toLowerCase()}[${attr}="${el.getAttribute(attr)}"]`;
        }
    }

    // Path-based selector
    let path = [];
    let current = el;
    while (current && current.nodeType === 1 && current !== document.body) {
        let slug = current.tagName.toLowerCase();

        if (current.classList.length) {
            const semanticClass = Array.from(current.classList)
                .find(c => /btn|button|submit|form|input|field/i.test(c));
            if (semanticClass) {
                slug += `.${semanticClass}`;
            } else {
                const firstClass = current.classList[0];
                if (firstClass && !/hover|active|focus|visible/i.test(firstClass)) {
                    slug += `.${firstClass}`;
                }
            }
        }

        // Add nth-of-type for disambiguation
        let sibling = current.previousElementSibling;
        let count = 1;
        while (sibling) {
            if (sibling.tagName === current.tagName) count++;
            sibling = sibling.previousElementSibling;
        }
        if (count > 1) slug += `:nth-of-type(${count})`;

        path.unshift(slug);
        current = current.parentNode;
    }
    return path.join(' > ');
}

/* ==========================================================================
   SUBMIT BUTTON DETECTION - Multi-Criteria Scoring System
   ========================================================================== */

/**
 * Extract button metadata for scoring
 */
function extractButtonMetadata(btn, formRect) {
    const tag = btn.tagName.toLowerCase();
    const type = (btn.getAttribute('type') || '').toLowerCase();
    const role = btn.getAttribute('role');
    const rect = btn.getBoundingClientRect();
    const style = window.getComputedStyle(btn);

    const innerText = (btn.innerText || '').toLowerCase().trim();
    const value = (btn.value || '').toLowerCase().trim();
    const ariaLabel = (btn.getAttribute('aria-label') || '').toLowerCase().trim();
    const title = (btn.getAttribute('title') || '').toLowerCase().trim();
    const id = (btn.id || '').toLowerCase();
    const name = (btn.getAttribute('name') || '').toLowerCase();
    const className = (btn.className || '').toLowerCase();

    const combinedText = [innerText, value, ariaLabel, title].filter(Boolean).join(' ');
    const combinedAttrs = [id, name, className].filter(Boolean).join(' ');

    return {
        tag, type, role, rect, style,
        innerText, value, ariaLabel, title, id, name, className,
        combinedText, combinedAttrs, formRect
    };
}

/**
 * CRITERIA 1: Structural/Semantic (0-30 points)
 */
function scoreStructural(meta) {
    let score = 0;

    if (meta.type === 'submit') score += 30;
    else if (meta.type === 'button') score += 8;

    if (meta.tag === 'button' && !meta.type) score += 12;
    if (meta.role === 'button') score += 5;

    // Negative signals
    if (meta.type === 'reset') score -= 30;
    if (meta.type === 'checkbox' || meta.type === 'radio') score -= 50;

    return score;
}

/**
 * CRITERIA 2: Text Content (0-35 points)
 */
function scoreTextContent(meta) {
    let score = 0;

    // Primary action keywords
    const primaryActions = {
        'submit': 30, 'send': 25, 'save': 22,
        'login': 25, 'log in': 25, 'sign in': 25, 'signin': 25,
        'sign up': 25, 'signup': 25, 'register': 25,
        'pay': 25, 'checkout': 25, 'purchase': 25, 'buy': 23,
        'continue': 20, 'next': 18, 'proceed': 20,
        'confirm': 22, 'apply': 20, 'create': 18,
        'search': 20, 'go': 12
    };

    for (const [keyword, points] of Object.entries(primaryActions)) {
        if (meta.combinedText.includes(keyword)) {
            score = Math.max(score, points);
            break;
        }
    }

    // Attribute-based keywords
    if (/submit|btn-primary|btn-success|action|primary|cta/i.test(meta.combinedAttrs)) {
        score += 10;
    }

    // Negative keywords
    const negativePatterns = {
        'cancel': -40, 'close': -35, 'dismiss': -35,
        'back': -30, 'previous': -25, 'reset': -35,
        'delete': -30, 'skip': -25
    };

    for (const [keyword, penalty] of Object.entries(negativePatterns)) {
        if (meta.combinedText.includes(keyword)) {
            score += penalty;
            break;
        }
    }

    return score;
}

/**
 * CRITERIA 3: Visual Style (0-20 points)
 */
function scoreVisualStyle(meta) {
    let score = 0;

    const bg = meta.style.backgroundColor;
    const isTransparent = bg === 'rgba(0, 0, 0, 0)' || bg === 'transparent';
    const isWhite = bg === 'rgb(255, 255, 255)';

    if (!isTransparent && !isWhite) {
        score += 8;

        const colorMatch = bg.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
        if (colorMatch) {
            const [_, r, g, b] = colorMatch.map(Number);
            if (b > 150 && b > r && b > g) score += 4; // Blue
            if (g > 150 && g > r && g > b) score += 5; // Green
            if (r > 150 && r > b && (r - g) < 80) score += 3; // Orange/Red
        }
    }

    // Size analysis
    const area = meta.rect.width * meta.rect.height;
    if (area > 8000) score += 5;
    else if (area > 4000) score += 3;
    else if (area < 1500) score -= 2;

    // Font weight
    const fontWeight = parseInt(meta.style.fontWeight) || 400;
    if (fontWeight >= 600) score += 3;

    // Cursor
    if (meta.style.cursor === 'pointer') score += 2;

    // Button classes
    if (/btn-primary|btn-success|btn-action|btn-cta/i.test(meta.className)) score += 6;

    return score;
}

/**
 * CRITERIA 4: Position (0-20 points)
 */
function scorePosition(meta) {
    let score = 0;
    if (!meta.formRect) return 0;

    const formRect = meta.formRect;
    const btnRect = meta.rect;

    // Vertical position
    const isBelow = btnRect.top > formRect.bottom;
    const isInside = btnRect.top >= formRect.top && btnRect.bottom <= formRect.bottom;

    if (isBelow) {
        const gap = btnRect.top - formRect.bottom;
        if (gap < 200) score += 15;
        else if (gap < 400) score += 8;
    } else if (isInside) {
        const relativePosition = (btnRect.top - formRect.top) / formRect.height;
        if (relativePosition > 0.7) score += 12;
        else if (relativePosition > 0.4) score += 6;
        else score += 2;
    }

    // Horizontal alignment
    const formCenterX = formRect.left + formRect.width / 2;
    const btnCenterX = btnRect.left + btnRect.width / 2;
    const horizontalOffset = Math.abs(btnCenterX - formCenterX);

    if (horizontalOffset < 50) score += 3;
    else if (btnRect.right > formRect.right - 100) score += 2;

    return score;
}

/**
 * CRITERIA 5: Context (0-15 points)
 */
function scoreContext(meta, allButtons) {
    let score = 0;

    if (allButtons && allButtons.length > 1) {
        const buttonIndex = allButtons.indexOf(meta);
        if (buttonIndex === allButtons.length - 1) score += 5;
        else if (buttonIndex === 0 && allButtons.length > 2) score -= 3;
    }

    // Parent container hints
    if (/footer|actions?|buttons?|controls?|submit/i.test(meta.className)) {
        score += 5;
    }

    return score;
}

/**
 * Master scoring function
 */
function scoreButton(btn, formRect, allButtons) {
    const meta = extractButtonMetadata(btn, formRect);

    // Basic interactivity check
    const isInteractive = (
        meta.tag === 'button' ||
        (meta.tag === 'input' && ['submit', 'button', 'image'].includes(meta.type)) ||
        (meta.tag === 'a' && (btn.href === '#' || btn.href === 'javascript:void(0)')) ||
        meta.role === 'button' ||
        meta.style.cursor === 'pointer'
    );

    if (!isInteractive) return -1000;

    const structural = scoreStructural(meta);
    const textContent = scoreTextContent(meta);
    const visualStyle = scoreVisualStyle(meta);
    const position = scorePosition(meta);
    const context = scoreContext(meta, allButtons);

    return structural + textContent + visualStyle + position + context;
}

/* ==========================================================================
   FORM DETECTION
   ========================================================================== */

/**
 * Main form detection function
 */
/**
 * Main form detection function
 */
function detectForms() {
    const all = getAllElements();
    const detected = [];
    const claimedInputs = new Set();
    let formCounter = 0;

    // A. Find form containers
    let containers = [];

    // A1. Standard <form> tags
    all.filter(e => e.tagName === 'FORM' && isVisible(e)).forEach(f => containers.push(f));

    // A2. Heuristic Div Forms
    const inputs = all.filter(e => {
        const t = e.tagName.toLowerCase();
        return (t === 'input' && !['hidden', 'submit', 'button', 'image'].includes(e.type)) ||
            t === 'select' ||
            t === 'textarea';
    }).filter(isVisible);

    const candidates = new Set();
    inputs.forEach(input => {
        let p = input.parentElement;
        let depth = 0;
        // Search up to 6 levels or until body/shadow root
        while (p && p !== document.body && depth < 6 && !(p instanceof ShadowRoot)) {
            const siblings = p.querySelectorAll('input:not([type="hidden"]), select, textarea');
            const visibleSiblings = Array.from(siblings).filter(isVisible);

            // If a container has at least one visible input, consider it a candidate
            if (visibleSiblings.length >= 1) {
                if (['DIV', 'SECTION', 'FORM', 'MAIN', 'ARTICLE', 'FIELDSET'].includes(p.tagName)) {
                    candidates.add(p);
                }
            }
            if (p.tagName === 'FORM') break;
            p = p.parentElement;
            depth++;
        }
    });

    const sortedCandidates = Array.from(candidates).sort((a, b) => {
        const depthA = getDepth(a);
        const depthB = getDepth(b);
        return depthB - depthA;
    });

    const finalCandidates = [];
    sortedCandidates.forEach(c => {
        const alreadyCovered = containers.some(f => f.contains(c));
        if (!alreadyCovered) finalCandidates.push(c);
    });

    containers = containers.concat(finalCandidates);

    // B. Process each container
    containers.forEach(container => {
        const cInputs = Array.from(container.querySelectorAll('input:not([type="hidden"]), select, textarea'))
            .filter(isVisible);

        const freeInputs = cInputs.filter(i => !claimedInputs.has(i));

        // Allow single input forms (e.g. search / email subscribe)
        if (freeInputs.length === 0) return;

        // If it's not a FORM tag, require stricter density or multiple fields
        if (container.tagName !== 'FORM' && (freeInputs.length / cInputs.length < 0.6)) return;

        freeInputs.forEach(i => claimedInputs.add(i));

        // Map Fields
        const fields = cInputs.map(el => {
            const name = el.name || el.id || el.getAttribute('aria-label') || '';
            const type = el.type || 'text';
            const tagName = el.tagName.toLowerCase();
            let hint = type;
            const ctx = (name + " " + (el.placeholder || "") + " " + (el.className || "")).toLowerCase();

            if (ctx.match(/email|mail/)) hint = 'email';
            else if (ctx.match(/pass|secret|pwd/)) hint = 'password';
            else if (ctx.match(/tel|phone|cel|mobile/)) hint = 'tel';
            else if (ctx.match(/search|query|find/)) hint = 'search';
            else if (ctx.match(/amount|qty|price|num/)) hint = 'number';
            else if (ctx.match(/date|year|month|day/)) hint = 'date';
            else if (tagName === 'select') hint = 'select';

            let options = [];
            if (tagName === 'select') {
                options = Array.from(el.options)
                    .filter(opt => opt.value && opt.value !== '')
                    .map(opt => ({
                        value: opt.value,
                        text: opt.text.trim()
                    }));
            }

            return {
                selector: getSelector(el),
                tagName: tagName,
                type: type,
                typeHint: hint,
                name: name,
                required: el.required || el.getAttribute('aria-required') === 'true',
                label: el.placeholder || name,
                options: options
            };
        });

        // C. Enhanced Button Detection
        let potentials = [];

        // 1. Scan INSIDE container
        potentials = potentials.concat(
            Array.from(container.querySelectorAll('button, input[type="submit"], input[type="button"], input[type="image"], a, [role="button"]'))
        );

        // 2. Scan SIBLINGS (Extended Range)
        let sib = container.nextElementSibling;
        let lookahead = 6;  // Increased lookahead
        while (sib && lookahead > 0) {
            if (isVisible(sib)) {
                if (['BUTTON', 'INPUT', 'A'].includes(sib.tagName)) potentials.push(sib);
                potentials = potentials.concat(
                    Array.from(sib.querySelectorAll('button, input[type="submit"], input[type="button"], a, [role="button"]'))
                );
            }
            sib = sib.nextElementSibling;
            lookahead--;
        }

        // 3. Scan PREVIOUS SIBLINGS
        sib = container.previousElementSibling;
        let lookbehind = 2;
        while (sib && lookbehind > 0) {
            if (isVisible(sib)) {
                if (['BUTTON', 'INPUT', 'A'].includes(sib.tagName)) potentials.push(sib);
                potentials = potentials.concat(
                    Array.from(sib.querySelectorAll('button, input[type="submit"], input[type="button"], a, [role="button"]'))
                );
            }
            sib = sib.previousElementSibling;
            lookbehind--;
        }

        // Deduplicate & Filter
        potentials = [...new Set(potentials)].filter(isVisible);

        // Score
        const containerRect = container.getBoundingClientRect();
        const scoredButtons = potentials.map(btn => ({
            element: btn,
            score: scoreButton(btn, containerRect, potentials),
            selector: getSelector(btn)
        }))
            .filter(b => b.score > 0)  // Filter out negative scores
            .sort((a, b) => b.score - a.score);

        // Return TOP 3
        const topButtons = scoredButtons.slice(0, 3).map(b => b.selector);

        if (fields.length > 0) {
            detected.push({
                id: container.id || `form_${formCounter++}`,
                containerSelector: getSelector(container),
                fields: fields,
                submitSelectors: topButtons,
                submitScores: scoredButtons.slice(0, 3).map(b => ({
                    selector: b.selector,
                    score: b.score
                })),
                isFormTag: container.tagName === 'FORM',
                action: container.action || container.getAttribute('action') || ''
            });
        }
    });

    return detected;
}

function getDepth(el) {
    let d = 0;
    while (el.parentNode) { d++; el = el.parentNode; }
    return d;
}

// Expose to window
window.detectForms = detectForms;


/* ==========================================================================
   ERROR DETECTION ENGINE
   ========================================================================== */

function detectValidationErrors(containerSelector) {
    if (!containerSelector) return [];

    const container = document.querySelector(containerSelector);
    if (!container) return [];

    const errors = new Set();

    function isRedText(el) {
        const style = window.getComputedStyle(el);
        const color = style.color;
        // Simple RGB/RGBA red component dominance check
        const match = color.match(/rgb\((\d+),\s*(\d+),\s*(\d+)\)/);
        if (match) {
            const [_, r, g, b] = match.map(Number);
            // Red dominates and is reasonably bright
            return (r > 150 && g < 100 && b < 100);
        }
        return false;
    }

    function scanForErrors(root) {
        const allElements = Array.from(root.querySelectorAll('*'));

        allElements.forEach(el => {
            if (!isVisible(el)) return;

            const text = el.innerText ? el.innerText.trim() : '';
            if (!text || text.length > 250) return; // Ignore long blocks

            let isError = false;

            // 1. Semantic Check
            if (el.getAttribute('role') === 'alert') isError = true;
            if (el.getAttribute('aria-live') === 'assertive') isError = true;
            if (el.getAttribute('aria-invalid') === 'true') isError = true;

            const classList = el.className.toLowerCase();
            if (classList.includes('error') ||
                classList.includes('invalid') ||
                classList.includes('text-red') ||
                classList.includes('text-danger') ||
                classList.includes('validation') ||
                classList.includes('alert-danger')) {
                isError = true;
            }

            // 2. Visual Check (Red Text)
            // Skip common non-error red things (buttons, links)
            if (!isError && isRedText(el)) {
                const tag = el.tagName;
                if (!['BUTTON', 'A', 'INPUT', 'LABEL'].includes(tag)) {
                    isError = true;
                }
            }

            // 3. Heuristic Keyword Check (closest to inputs)
            if (!isError && text.length < 150) {
                const errorPatterns = /required|invalid|error|incorrect|must|cannot|failed|please|check|enter|provide|missing/i;
                if (errorPatterns.test(text)) {
                    // Check context: is it near a form field?
                    const nearInput = el.closest('.form-group, .form-field, .input-group, fieldset');
                    if (nearInput) isError = true;
                }
            }

            if (isError && text) {
                errors.add(text);
            }
        });
    }

    // Scan inside container
    scanForErrors(container);

    // Scan siblings (often alerts are placed right above/below the form)
    let sibling = container.nextElementSibling;
    if (sibling && isVisible(sibling)) scanForErrors(sibling);

    sibling = container.previousElementSibling;
    if (sibling && isVisible(sibling)) scanForErrors(sibling);

    return Array.from(errors);
}

window.detectValidationErrors = detectValidationErrors;
