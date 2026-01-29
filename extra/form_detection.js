// form_detection.js (Production Ready v8 - Enhanced Error Detection)
// Industry-grade form detection with improved real-time validation error capture.

/* ==========================================================================
   DOM TRAVERSAL & UTILS
   ========================================================================== */

/**
 * Recursively find all elements, piercing Shadow DOM boundaries.
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
 * Check if element is visible to the human eye.
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
 * Generate a robust CSS selector for automation.
 */
function getSelector(el) {
    if (!el || el.nodeType !== 1) return '';
    if (el.id) return `#${el.id}`;

    // Automation Hooks (High Priority)
    const testAttrs = ['data-testid', 'data-qa', 'data-cy', 'data-slot', 'name', 'aria-label'];
    for (const attr of testAttrs) {
        if (el.hasAttribute(attr)) return `${el.tagName.toLowerCase()}[${attr}="${el.getAttribute(attr)}"]`;
    }

    // Path Fallback
    let path = [];
    let current = el;
    while (current && current.nodeType === 1 && current !== document.body && !(current instanceof ShadowRoot)) {
        let slug = current.tagName.toLowerCase();
        if (current.classList.length) {
            // Pick a semantic class, ignoring common utilities
            const ignorePattern = /hover|active|focus|visible|open|dirty|touched|ng-|v-|react|^p-\d|^m-\d|^flex|^grid|^block|^w-\d|^h-\d|^text-[a-z]|^bg-[a-z]|^border|^rounded|^items-|^justify-|^gap-/;
            const validClass = Array.from(current.classList).find(c => !ignorePattern.test(c));

            // Prefer classes with "btn", "form", "input", "submit"
            const semanticClass = Array.from(current.classList).find(c => /btn|button|submit|action|form|input|field/i.test(c));

            if (semanticClass) {
                slug += `.${semanticClass}`;
            } else if (validClass) {
                slug += `.${validClass}`;
            }
        }

        // Nth-of-type for disambiguation
        let sibling = current.previousElementSibling;
        let c = 1;
        while (sibling) {
            if (sibling.tagName === current.tagName) c++;
            sibling = sibling.previousElementSibling;
        }
        if (c > 1) slug += `:nth-of-type(${c})`;

        path.unshift(slug);
        current = current.parentNode;
    }
    return path.join(' > ');
}

/* ==========================================================================
   ENHANCED BUTTON DETECTION ENGINE
   Industry-grade multi-criteria scoring system
   ========================================================================== */

/**
 * Comprehensive button metadata extraction.
 */
function extractButtonMetadata(btn, formRect) {
    const tag = btn.tagName.toLowerCase();
    const type = (btn.getAttribute('type') || '').toLowerCase();
    const role = btn.getAttribute('role');
    const rect = btn.getBoundingClientRect();
    const style = window.getComputedStyle(btn);

    // Extract all text sources
    const innerText = (btn.innerText || '').toLowerCase().trim();
    const value = (btn.value || '').toLowerCase().trim();
    const ariaLabel = (btn.getAttribute('aria-label') || '').toLowerCase().trim();
    const title = (btn.getAttribute('title') || '').toLowerCase().trim();
    const id = (btn.id || '').toLowerCase();
    const name = (btn.getAttribute('name') || '').toLowerCase();
    const className = (btn.className || '').toLowerCase();

    // Combine all text for comprehensive analysis
    const combinedText = [innerText, value, ariaLabel, title].filter(Boolean).join(' ');
    const combinedAttrs = [id, name, className].filter(Boolean).join(' ');

    return {
        tag,
        type,
        role,
        rect,
        style,
        innerText,
        value,
        ariaLabel,
        title,
        id,
        name,
        className,
        combinedText,
        combinedAttrs,
        formRect
    };
}

/**
 * CRITERIA 1: Structural/Semantic Analysis (0-30 points)
 */
function scoreStructural(meta) {
    let score = 0;

    if (meta.type === 'submit') {
        score += 30;
    } else if (meta.type === 'button') {
        score += 8;
    }

    if (meta.tag === 'button' && !meta.type) {
        score += 12;
    }

    if (meta.role === 'button') {
        score += 5;
    }

    if (meta.type === 'reset') score -= 30;
    if (meta.type === 'checkbox' || meta.type === 'radio') score -= 50;

    return score;
}

/**
 * CRITERIA 2: Text/Content Analysis (0-35 points)
 */
function scoreTextContent(meta) {
    let score = 0;

    const primaryActions = {
        'login': 25, 'log in': 25, 'sign in': 25, 'signin': 25,
        'sign up': 25, 'signup': 25, 'register': 25,
        'submit': 30, 'send': 25, 'save': 22,
        'pay': 25, 'checkout': 25, 'purchase': 25, 'buy': 23,
        'order': 20, 'book': 20, 'reserve': 20,
        'continue': 20, 'next': 18, 'proceed': 20,
        'confirm': 22, 'apply': 20, 'create': 18,
        'search': 20, 'find': 15, 'go': 12,
        'update': 18, 'publish': 20, 'post': 18,
        'upload': 18, 'download': 15,
        'subscribe': 18, 'join': 18, 'contact': 18,
        'request': 16, 'invite': 16,
        'finish': 18, 'complete': 18, 'done': 16,
        'accept': 16, 'agree': 16, 'verify': 18
    };

    for (const [keyword, points] of Object.entries(primaryActions)) {
        if (meta.combinedText.includes(keyword)) {
            score = Math.max(score, points);
            break;
        }
    }

    const secondaryActions = /submit|add|new|start|begin|enable|activate|get|claim|redeem/i;
    if (!score && secondaryActions.test(meta.combinedText)) {
        score += 12;
    }

    const attrKeywords = /submit|btn-primary|btn-success|action|primary|cta|call-to-action/i;
    if (attrKeywords.test(meta.combinedAttrs)) {
        score += 10;
    }

    const negativePatterns = {
        'cancel': -40, 'close': -35, 'dismiss': -35,
        'back': -30, 'previous': -25, 'prev': -25,
        'reset': -35, 'clear': -30, 'delete': -30,
        'remove': -28, 'edit': -20, 'change': -15,
        'forgot': -25, 'help': -20, 'support': -20,
        'learn more': -18, 'details': -15, 'info': -15,
        'skip': -25, 'later': -20, 'maybe': -20,
        'no': -15, 'deny': -20, 'decline': -20
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
 * CRITERIA 3: Visual/Style Analysis (0-20 points)
 */
function scoreVisualStyle(meta) {
    let score = 0;

    const bg = meta.style.backgroundColor;
    const isTransparent = bg === 'rgba(0, 0, 0, 0)' || bg === 'transparent';
    const isWhite = bg === 'rgb(255, 255, 255)' || bg === '#ffffff' || bg === '#fff';

    if (!isTransparent && !isWhite) {
        score += 8;

        const colorMatch = bg.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
        if (colorMatch) {
            const [_, r, g, b] = colorMatch.map(Number);
            if (b > 150 && b > r && b > g) score += 4;
            if (g > 150 && g > r && g > b) score += 5;
            if (r > 150 && r > b && (r - g) < 80) score += 3;
        }
    }

    const area = meta.rect.width * meta.rect.height;
    if (area > 8000) score += 5;
    else if (area > 4000) score += 3;
    else if (area < 1500) score -= 2;

    const fontWeight = parseInt(meta.style.fontWeight) || 400;
    if (fontWeight >= 600) score += 3;

    if (meta.style.cursor === 'pointer') score += 2;

    const buttonClasses = /btn-primary|btn-success|btn-action|btn-cta|primary|success|action-button/i;
    if (buttonClasses.test(meta.className)) score += 6;

    return score;
}

/**
 * CRITERIA 4: Geometric/Positional Analysis (0-20 points)
 */
function scorePosition(meta) {
    let score = 0;

    if (!meta.formRect) return 0;

    const formRect = meta.formRect;
    const btnRect = meta.rect;

    const isBelow = btnRect.top > formRect.top;
    const isAbove = btnRect.bottom < formRect.bottom;
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
    } else if (isAbove) {
        score -= 5;
    }

    const formCenterX = formRect.left + formRect.width / 2;
    const btnCenterX = btnRect.left + btnRect.width / 2;
    const horizontalOffset = Math.abs(btnCenterX - formCenterX);

    if (horizontalOffset < 50) {
        score += 3;
    } else if (btnRect.right > formRect.right - 100) {
        score += 2;
    }

    return score;
}

/**
 * CRITERIA 5: Context Analysis (0-15 points)
 */
function scoreContext(meta, allButtons) {
    let score = 0;

    if (allButtons && allButtons.length > 1) {
        const buttonIndex = allButtons.indexOf(meta);
        if (buttonIndex === allButtons.length - 1) {
            score += 5;
        } else if (buttonIndex === 0 && allButtons.length > 2) {
            score -= 3;
        }
    }

    const hasFormParent = (() => {
        let p = document.querySelector(`${meta.tag}[class="${meta.className}"]`);
        while (p && p !== document.body) {
            if (p.tagName === 'FORM') return true;
            p = p.parentElement;
        }
        return false;
    })();

    if (hasFormParent) score += 5;

    const parentClass = meta.className;
    if (/footer|actions?|buttons?|controls?|submit/i.test(parentClass)) {
        score += 5;
    }

    return score;
}

/**
 * MASTER SCORING FUNCTION
 */
function scoreButton(btn, formRect, allButtons) {
    const meta = extractButtonMetadata(btn, formRect);

    const isInteractive = (
        meta.tag === 'button' ||
        (meta.tag === 'input' && ['submit', 'button', 'image'].includes(meta.type)) ||
        (meta.tag === 'a' && (btn.href === '#' || btn.href === 'javascript:void(0)' || meta.className.includes('btn'))) ||
        meta.role === 'button' ||
        meta.style.cursor === 'pointer'
    );

    if (!isInteractive) return -1000;

    const structural = scoreStructural(meta);
    const textContent = scoreTextContent(meta);
    const visualStyle = scoreVisualStyle(meta);
    const position = scorePosition(meta);
    const context = scoreContext(meta, allButtons);

    const totalScore = structural + textContent + visualStyle + position + context;

    if (window.__DEBUG_BUTTON_SCORING) {
        console.log('Button Score Breakdown:', {
            selector: getSelector(btn),
            text: meta.combinedText.substring(0, 30),
            structural,
            textContent,
            visualStyle,
            position,
            context,
            total: totalScore
        });
    }

    return totalScore;
}

/* ==========================================================================
   MAIN DETECTION LOGIC
   ========================================================================== */

function detectForms() {
    const all = getAllElements();
    const detected = [];
    const claimedInputs = new Set();
    let formCounter = 0;

    // A. IDENTIFY FORM CONTAINERS
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
        while (p && p !== document.body && depth < 6 && !(p instanceof ShadowRoot)) {
            const siblings = p.querySelectorAll('input:not([type="hidden"]), select, textarea');
            const visibleSiblings = Array.from(siblings).filter(isVisible);

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

    // B. PROCESS CONTAINERS
    containers.forEach(container => {
        const cInputs = Array.from(container.querySelectorAll('input:not([type="hidden"]), select, textarea'))
            .filter(isVisible);

        const freeInputs = cInputs.filter(i => !claimedInputs.has(i));

        if (freeInputs.length === 0) return;

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

        // C. ENHANCED BUTTON DETECTION
        let potentials = [];

        potentials = potentials.concat(
            Array.from(container.querySelectorAll('button, input[type="submit"], input[type="button"], input[type="image"], a, [role="button"]'))
        );

        let sib = container.nextElementSibling;
        let lookahead = 6;
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

        potentials = [...new Set(potentials)].filter(isVisible);

        const containerRect = container.getBoundingClientRect();
        const scoredButtons = potentials.map(btn => ({
            element: btn,
            score: scoreButton(btn, containerRect, potentials),
            selector: getSelector(btn)
        }))
            .filter(b => b.score > 0)
            .sort((a, b) => b.score - a.score);

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

window.detectForms = detectForms;

/* ==========================================================================
   ENHANCED ERROR DETECTION ENGINE
   Multi-strategy validation error detection with expanded coverage
   ========================================================================== */

/**
 * ENHANCED: Detect validation errors with multiple strategies
 */
function detectValidationErrors(containerSelector) {
    if (!containerSelector) return [];

    const container = document.querySelector(containerSelector);
    if (!container) return [];

    const errors = new Set();

    /**
     * Strategy 1: Color-based detection (red text)
     */
    function isRedText(el) {
        const style = window.getComputedStyle(el);
        const color = style.color;
        const match = color.match(/rgb\((\d+),\s*(\d+),\s*(\d+)\)/);
        if (match) {
            const [_, r, g, b] = match.map(Number);
            return (r > 150 && g < 100 && b < 100);
        }
        return false;
    }

    /**
     * Strategy 2: Background-based detection (red/pink backgrounds)
     */
    function hasErrorBackground(el) {
        const style = window.getComputedStyle(el);
        const bg = style.backgroundColor;
        const match = bg.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
        if (match) {
            const [_, r, g, b] = match.map(Number);
            // Red/pink background
            return (r > 200 && g < 150 && b < 150);
        }
        return false;
    }

    /**
     * Strategy 3: Border-based detection (red borders on invalid fields)
     */
    function hasErrorBorder(el) {
        const style = window.getComputedStyle(el);
        const borderColor = style.borderColor || style.borderTopColor;
        if (borderColor && borderColor !== 'initial' && borderColor !== 'inherit') {
            const match = borderColor.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
            if (match) {
                const [_, r, g, b] = match.map(Number);
                return (r > 150 && g < 100 && b < 100);
            }
        }
        return false;
    }

    /**
     * Main scanning function with all strategies
     */
    function scanForErrors(root) {
        const allElements = Array.from(root.querySelectorAll('*'));

        allElements.forEach(el => {
            if (!isVisible(el)) return;

            const text = el.innerText ? el.innerText.trim() : '';
            if (!text || text.length > 250) return;

            let isError = false;
            let detectionMethod = '';

            // ARIA attributes
            if (el.getAttribute('role') === 'alert') {
                isError = true;
                detectionMethod = 'aria-role-alert';
            }
            if (el.getAttribute('aria-live') === 'assertive' || el.getAttribute('aria-live') === 'polite') {
                isError = true;
                detectionMethod = 'aria-live';
            }
            if (el.getAttribute('aria-invalid') === 'true') {
                isError = true;
                detectionMethod = 'aria-invalid';
            }

            // Class-based detection (expanded patterns)
            const classList = el.className.toLowerCase();
            const errorClassPatterns = [
                'error', 'invalid', 'text-red', 'text-danger', 'validation',
                'alert-danger', 'form-error', 'field-error', 'input-error',
                'error-message', 'validation-error', 'help-block-error',
                'is-invalid', 'has-error', 'ng-invalid', 'is-danger'
            ];

            if (errorClassPatterns.some(pattern => classList.includes(pattern))) {
                isError = true;
                detectionMethod = 'css-class';
            }

            // Visual detection (color/background/border)
            if (!isError && isRedText(el)) {
                const tag = el.tagName;
                if (!['BUTTON', 'A', 'INPUT', 'LABEL', 'H1', 'H2', 'H3', 'H4', 'H5', 'H6'].includes(tag)) {
                    isError = true;
                    detectionMethod = 'red-text';
                }
            }

            if (!isError && hasErrorBackground(el)) {
                isError = true;
                detectionMethod = 'error-background';
            }

            // Content pattern matching
            if (!isError && text.length < 150) {
                const errorPatterns = /required|invalid|error|incorrect|must|cannot|failed|please|check|enter|provide|missing|field is|should|mandatory|not valid|not match|too short|too long|minimum|maximum/i;
                if (errorPatterns.test(text)) {
                    // Check if near a form field
                    const nearInput = el.closest('.form-group, .form-field, .input-group, .field, fieldset, .form-control') ||
                        el.parentElement?.querySelector('input, select, textarea');
                    if (nearInput) {
                        isError = true;
                        detectionMethod = 'content-pattern';
                    }
                }
            }

            // Check for invalid input fields themselves
            if (el.tagName === 'INPUT' || el.tagName === 'SELECT' || el.tagName === 'TEXTAREA') {
                if (el.getAttribute('aria-invalid') === 'true' || hasErrorBorder(el)) {
                    // Look for associated error message
                    const errorId = el.getAttribute('aria-describedby');
                    if (errorId) {
                        const errorEl = document.getElementById(errorId);
                        if (errorEl && errorEl.innerText) {
                            errors.add(errorEl.innerText.trim());
                        }
                    }

                    // Check siblings for error messages
                    const siblings = [el.nextElementSibling, el.previousElementSibling];
                    siblings.forEach(sib => {
                        if (sib && isVisible(sib)) {
                            const sibText = sib.innerText?.trim();
                            if (sibText && sibText.length < 150 && /error|invalid|required|must|cannot/i.test(sibText)) {
                                errors.add(sibText);
                            }
                        }
                    });

                    // Check parent's children
                    const parent = el.parentElement;
                    if (parent) {
                        Array.from(parent.children).forEach(child => {
                            if (child !== el && isVisible(child)) {
                                const childText = child.innerText?.trim();
                                if (childText && childText.length < 150 &&
                                    (isRedText(child) || hasErrorBackground(child) ||
                                        /error|invalid|required/i.test(child.className))) {
                                    errors.add(childText);
                                }
                            }
                        });
                    }
                }
            }

            if (isError && text) {
                if (window.__DEBUG_ERROR_DETECTION) {
                    console.log(`Error detected via ${detectionMethod}:`, text);
                }
                errors.add(text);
            }
        });
    }

    // Scan container
    scanForErrors(container);

    // Scan immediate siblings (errors might render outside form)
    let sibling = container.nextElementSibling;
    let checkCount = 0;
    while (sibling && checkCount < 3) {
        if (isVisible(sibling)) {
            scanForErrors(sibling);
        }
        sibling = sibling.nextElementSibling;
        checkCount++;
    }

    sibling = container.previousElementSibling;
    checkCount = 0;
    while (sibling && checkCount < 2) {
        if (isVisible(sibling)) {
            scanForErrors(sibling);
        }
        sibling = sibling.previousElementSibling;
        checkCount++;
    }

    // Also check parent container (errors might be rendered at parent level)
    if (container.parentElement) {
        const parent = container.parentElement;
        Array.from(parent.children).forEach(child => {
            if (child !== container && isVisible(child)) {
                const childClasses = child.className.toLowerCase();
                if (childClasses.includes('error') || childClasses.includes('alert') || childClasses.includes('validation')) {
                    scanForErrors(child);
                }
            }
        });
    }

    return Array.from(errors);
}

window.detectValidationErrors = detectValidationErrors;

// Enable debug modes:
// window.__DEBUG_BUTTON_SCORING = true;
// window.__DEBUG_ERROR_DETECTION = true;