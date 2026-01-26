/**
 * HTMX-Alpine Bridge Utilities
 * 
 * Global Setup File
 * 
 * This file sets up application-wide HTMX-Alpine integration that persists for the
 * lifetime of the application. Event listeners are intentionally global and
 * do not require cleanup.
 * 
 * Global setup files vs Component-scoped:
 * - Global: Application-wide, persists for app lifetime, no cleanup needed
 * - Component-scoped: Per-component, requires destroy() cleanup
 * 
 * Utilities for better integration between HTMX and Alpine.js
 */

import Alpine from 'alpinejs';

/**
 * Preserve Alpine state during HTMX swaps
 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function preserveAlpineState(element: HTMLElement): Record<string, any> {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const state: Record<string, any> = {};
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const alpineData = (element as any)._x_dataStack;

    if (alpineData && alpineData.length > 0) {
        const data = alpineData[alpineData.length - 1];
        // Store non-function, non-internal properties
        Object.keys(data).forEach(key => {
            if (typeof data[key] !== 'function' && !key.startsWith('$') && !key.startsWith('_')) {
                try {
                    // Only store serializable data
                    JSON.stringify(data[key]);
                    state[key] = data[key];
                } catch {
                    // Skip non-serializable data
                }
            }
        });
    }

    return state;
}

/**
 * Restore Alpine state after HTMX swap
 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function restoreAlpineState(element: HTMLElement, state: Record<string, any>): void {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const alpineData = (element as any)._x_dataStack;

    if (alpineData && alpineData.length > 0) {
        const data = alpineData[alpineData.length - 1];
        Object.keys(state).forEach(key => {
            if (data.hasOwnProperty(key)) {
                data[key] = state[key];
            }
        });
    }
}

/**
 * Smart re-initialization of Alpine components after HTMX swap
 * Initializes new Alpine components that weren't handled by morph
 */
export function reinitializeAlpine(container: HTMLElement): void {
    // Find all elements with x-data that need initialization
    const alpineElements = container.querySelectorAll('[x-data]');

    alpineElements.forEach((el: Element) => {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const htmlEl = el as any;

        // Skip if already initialized by Alpine
        if (htmlEl._x_dataStack) {
            // Element already has Alpine data - morph handled it
            return;
        }

        // Initialize new Alpine components
        Alpine.initTree(htmlEl);
    });
}

/**
 * Use Alpine.morph to update DOM while preserving Alpine state
 * This is the key function for HTMX + Alpine integration
 */
export function morphElement(target: HTMLElement, newContent: string): boolean {
    // Check if Alpine.morph is available
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    if (typeof (Alpine as any).morph !== 'function') {
        return false; // Morph not available, use fallback
    }

    try {
        // Create a temporary container to parse the new HTML
        const temp = document.createElement('div');
        temp.innerHTML = newContent;

        // Get the new content element
        const newElement = temp.firstElementChild as HTMLElement;

        if (!newElement) {
            return false;
        }

        // Use Alpine.morph to update the DOM while preserving state
        // This will:
        // 1. Update the DOM to match new content
        // 2. Preserve Alpine component state
        // 3. Preserve form input values
        // 4. Keep focus where possible
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        (Alpine as any).morph(target, newElement, {
            updating: (from: HTMLElement, to: HTMLElement, _childrenOnly: () => void, skip: () => void) => {
                // Preserve certain attributes during morph
                if (from.hasAttribute('x-data') && to.hasAttribute('x-data')) {
                    // Let Alpine handle x-data elements
                    return;
                }

                // Skip morphing elements with data-morph-ignore
                if (from.hasAttribute('data-morph-ignore')) {
                    skip();
                    return;
                }
            },
            key: (el: HTMLElement) => {
                // Use data-morph-key or id for element matching
                return el.getAttribute('data-morph-key') || el.id || undefined;
            },
            lookahead: true // Look ahead for better matching
        });

        return true;
    } catch (error) {
        console.warn('[htmx-alpine-bridge] Morph failed, falling back to standard swap:', error);
        return false;
    }
}

/**
 * Check if Alpine.morph is available
 */
export function isMorphAvailable(): boolean {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    return typeof (Alpine as any).morph === 'function';
}

/**
 * Sync Alpine state with HTMX events
 */
export function syncAlpineWithHTMX(): void {
    // Set up global HTMX event handlers for Alpine state management

    document.body.addEventListener('htmx:beforeRequest', ((event: CustomEvent) => {
        const target = event.detail.elt as HTMLElement;

        // Add loading class to Alpine components
        const alpineElements = target.querySelectorAll('[x-data]');
        alpineElements.forEach((el: Element) => {
            const htmlEl = el as HTMLElement;
            htmlEl.classList.add('htmx-loading');

            // Try to set loading state if component has it
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            const alpineData = (htmlEl as any)._x_dataStack;
            if (alpineData && alpineData.length > 0) {
                const data = alpineData[alpineData.length - 1];
                if (typeof data.loading !== 'undefined') {
                    data.loading = true;
                }
            }
        });
    }) as EventListener);

    document.body.addEventListener('htmx:afterRequest', ((event: CustomEvent) => {
        const target = event.detail.elt as HTMLElement;

        // Remove loading class from Alpine components
        const alpineElements = target.querySelectorAll('[x-data]');
        alpineElements.forEach((el: Element) => {
            const htmlEl = el as HTMLElement;
            htmlEl.classList.remove('htmx-loading');

            // Try to clear loading state if component has it
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            const alpineData = (htmlEl as any)._x_dataStack;
            if (alpineData && alpineData.length > 0) {
                const data = alpineData[alpineData.length - 1];
                if (typeof data.loading !== 'undefined') {
                    data.loading = false;
                }
            }
        });
    }) as EventListener);
}

/**
 * Preserve and restore Alpine state for specific elements during HTMX swap
 */
export function preserveAlpineStateForSwap(
    oldElement: HTMLElement,
    newElement: HTMLElement
): void {
    // Preserve state from old element
    const preservedState = preserveAlpineState(oldElement);

    // Find matching element in new content
    const oldId = oldElement.id;
    const oldDataAttr = oldElement.getAttribute('x-data');

    let matchingElement: HTMLElement | null = null;

    if (oldId) {
        matchingElement = newElement.querySelector(`#${oldId}`) as HTMLElement;
    } else if (oldDataAttr) {
        // Try to find element with same x-data
        const candidates = newElement.querySelectorAll(`[x-data="${oldDataAttr}"]`);
        if (candidates.length === 1) {
            matchingElement = candidates[0] as HTMLElement;
        }
    }

    if (matchingElement && Object.keys(preservedState).length > 0) {
        // Initialize Alpine first
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        if (!(matchingElement as any)._x_dataStack) {
            Alpine.initTree(matchingElement);
        }

        // Restore state
        restoreAlpineState(matchingElement, preservedState);
    }
}

/**
 * Enhanced Alpine initialization with HTMX awareness
 * Sets up morph-based swapping for better state preservation
 */
export function initializeAlpineWithHTMX(): void {
    // Set up sync
    syncAlpineWithHTMX();

    // Intercept HTMX swaps to use Alpine.morph when available
    // This provides better state preservation than standard HTMX swaps
    document.body.addEventListener('htmx:beforeSwap', ((event: CustomEvent) => {
        const target = event.detail.target as HTMLElement;
        const serverResponse = event.detail.serverResponse as string;

        // Only use morph for innerHTML/outerHTML swaps on elements with Alpine data
        const swapStyle = event.detail.swapStyle || 'innerHTML';
        const hasAlpineData = target.querySelector('[x-data]') !== null || target.hasAttribute('x-data');

        if (hasAlpineData && isMorphAvailable() && (swapStyle === 'innerHTML' || swapStyle === 'outerHTML')) {
            // Check for hx-ext="alpine-morph" or data-use-morph attribute
            const useMorph = target.closest('[hx-ext*="alpine-morph"]') !== null ||
                target.hasAttribute('data-use-morph') ||
                target.closest('[data-use-morph]') !== null;

            if (useMorph) {
                // Try to use Alpine.morph for the swap
                const morphSuccess = morphElement(target, serverResponse);

                if (morphSuccess) {
                    // Morph succeeded - prevent default HTMX swap
                    event.detail.shouldSwap = false;

                    // Dispatch event to notify that morph completed
                    target.dispatchEvent(new CustomEvent('alpine:morphComplete', {
                        bubbles: true,
                        detail: { target }
                    }));

                    // Reinitialize any new Alpine components that were added
                    reinitializeAlpine(target);
                    return;
                }
            }
        }

        // If morph wasn't used, let HTMX do the standard swap
        // afterSwap handler will reinitialize Alpine
    }) as EventListener);

    // After standard HTMX swap - reinitialize new Alpine components
    document.body.addEventListener('htmx:afterSwap', ((event: CustomEvent) => {
        const target = event.detail.target as HTMLElement;

        // Reinitialize any Alpine components that weren't handled by morph
        reinitializeAlpine(target);
    }) as EventListener);
}
