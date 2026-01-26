/**
 * HTMX Lifecycle Handler
 * 
 * Global Setup File
 * 
 * This file sets up application-wide HTMX event listeners that persist for the
 * lifetime of the application. These listeners are intentionally global and
 * do not require cleanup.
 * 
 * Global setup files vs Component-scoped:
 * - Global: Application-wide, persists for app lifetime, no cleanup needed
 * - Component-scoped: Per-component, requires destroy() cleanup
 * 
 * Centralized handler for HTMX events, ensuring proper Alpine.js
 * integration, focus management, and state preservation.
 */
import Alpine from 'alpinejs';
import { showToast } from './alerts';
import { morphElement, isMorphAvailable, reinitializeAlpine } from './utils/htmx-alpine-bridge';
import { initializeTooltipsInContainer, destroyTooltipsInContainer } from './components/tooltip-manager';

// Track initialization state
let isInitialized = false;

/**
 * Initialize all HTMX lifecycle event handlers
 */
export function initHtmxLifecycle(): void {
    if (isInitialized) return;
    isInitialized = true;

    // ============================================
    // HTMX REQUEST LIFECYCLE
    // ============================================

    /**
     * Before HTMX sends a request - add loading states
     */
    document.body.addEventListener('htmx:beforeRequest', ((event: CustomEvent) => {
        const target = event.detail.elt as HTMLElement;

        // Add loading class to target element
        target.classList.add('htmx-loading');

        // Disable submit buttons in the target
        const submitButtons = target.querySelectorAll<HTMLButtonElement>('button[type="submit"]');
        submitButtons.forEach(btn => {
            btn.dataset.originalDisabled = btn.disabled.toString();
            btn.disabled = true;
        });
    }) as EventListener);

    /**
     * After HTMX request completes (success or failure)
     */
    document.body.addEventListener('htmx:afterRequest', ((event: CustomEvent) => {
        const target = event.detail.elt as HTMLElement;

        // Remove loading class
        target.classList.remove('htmx-loading');

        // Restore button states
        const submitButtons = target.querySelectorAll<HTMLButtonElement>('button[type="submit"]');
        submitButtons.forEach(btn => {
            const wasDisabled = btn.dataset.originalDisabled === 'true';
            btn.disabled = wasDisabled;
            delete btn.dataset.originalDisabled;
        });
    }) as EventListener);

    // ============================================
    // ALPINE.JS RE-INITIALIZATION AFTER SWAPS
    // ============================================

    /**
     * Before HTMX swaps content - try to use Alpine.morph for state preservation
     * This intercepts the swap and uses morph when available for elements with Alpine data
     */
    document.body.addEventListener('htmx:beforeSwap', ((event: CustomEvent) => {
        const target = event.detail.target as HTMLElement;
        const serverResponse = event.detail.serverResponse as string;
        const swapStyle = event.detail.swapStyle || 'innerHTML';

        // Check if this element or its children have Alpine data
        const hasAlpineData = target.querySelector('[x-data]') !== null || target.hasAttribute('x-data');

        // Only use morph for innerHTML/outerHTML swaps on Alpine elements
        // AND only when explicitly enabled via hx-ext or data-use-morph
        if (hasAlpineData && (swapStyle === 'innerHTML' || swapStyle === 'outerHTML')) {
            const useMorph = target.closest('[hx-ext*="alpine-morph"]') !== null ||
                target.hasAttribute('data-use-morph') ||
                target.closest('[data-use-morph]') !== null;

            if (useMorph && isMorphAvailable()) {
                // Use synchronously imported functions to avoid race condition
                const morphSuccess = morphElement(target, serverResponse);
                if (morphSuccess) {
                    // Morph handled the swap - prevent HTMX default swap
                    event.detail.shouldSwap = false;

                    // Dispatch completion event
                    target.dispatchEvent(new CustomEvent('alpine:morphComplete', {
                        bubbles: true,
                        detail: { target }
                    }));
                }
            }
        }
    }) as EventListener);

    /**
     * After HTMX swaps content - reinitialize Alpine components
     * This handles cases where morph wasn't used or new elements were added
     */
    document.body.addEventListener('htmx:afterSwap', ((event: CustomEvent) => {
        const target = event.detail.target as HTMLElement;

        // Use synchronously imported functions for Alpine reinitialization
        reinitializeAlpine(target);

        // Reinitialize tooltips in swapped content
        initializeTooltipsInContainer(target);
    }) as EventListener);

    /**
     * Before HTMX swap - cleanup event listeners and state
     */
    document.body.addEventListener('htmx:beforeSwap', ((event: CustomEvent) => {
        const target = event.detail.target as HTMLElement;

        // Destroy tooltips before swap to prevent orphaned elements
        destroyTooltipsInContainer(target);

        // Dispatch cleanup event for custom cleanup handlers
        target.dispatchEvent(new CustomEvent('alpine:beforeSwap', { bubbles: true }));
    }) as EventListener);

    // ============================================
    // FOCUS MANAGEMENT
    // ============================================

    /**
     * After swap - restore focus to appropriate element
     */
    document.body.addEventListener('htmx:afterSettle', ((event: CustomEvent) => {
        const target = event.detail.target as HTMLElement;

        // Look for element with autofocus attribute
        const autofocusEl = target.querySelector<HTMLElement>('[autofocus]');
        if (autofocusEl) {
            autofocusEl.focus();
            return;
        }

        // Look for data-focus-after-swap attribute
        const focusTarget = target.querySelector<HTMLElement>('[data-focus-after-swap]');
        if (focusTarget) {
            focusTarget.focus();
            return;
        }

        // If a form was submitted, focus first input
        if (target.tagName === 'FORM' || target.querySelector('form')) {
            const firstInput = target.querySelector<HTMLElement>('input:not([type="hidden"]), textarea, select');
            if (firstInput) {
                firstInput.focus();
            }
        }
    }) as EventListener);

    // ============================================
    // ERROR HANDLING
    // ============================================

    /**
     * Handle HTMX request errors
     */
    document.body.addEventListener('htmx:responseError', ((event: CustomEvent) => {
        const target = event.detail.target as HTMLElement;
        const xhr = event.detail.xhr as XMLHttpRequest;

        // Log error only in development to avoid polluting production logs
        // TODO: Integrate with error tracking service (e.g., Sentry) for production
        if (import.meta.env.DEV) {
            console.error('[HTMX Error]', {
                status: xhr.status,
                statusText: xhr.statusText,
                url: event.detail.pathInfo?.requestPath,
                target: target
            });
        }

        // Show error toast
        import('./alerts').then(({ showToast }) => {
            showToast({
                type: 'error',
                title: 'Request Failed',
                message: `Error ${xhr.status}: ${xhr.statusText || 'An error occurred'}`
            });
        }).catch(() => {
            // Fallback if import fails
            console.error('Failed to show error toast');
        });

        // Add error class to target
        target.classList.add('htmx-error');
        setTimeout(() => target.classList.remove('htmx-error'), 3000);
    }) as EventListener);

    /**
     * Handle HTMX send errors (network failures)
     */
    document.body.addEventListener('htmx:sendError', ((event: CustomEvent) => {
        const target = event.detail.elt as HTMLElement;

        // Log network error only in development to avoid polluting production logs
        // TODO: Integrate with error tracking service (e.g., Sentry) for production
        if (import.meta.env.DEV) {
            console.error('[HTMX Send Error]', event.detail);
        }

        // Show network error toast
        showToast({
            type: 'error',
            title: 'Network Error',
            message: 'Failed to connect to server. Please check your connection.'
        });

        target.classList.add('htmx-error');
        setTimeout(() => target.classList.remove('htmx-error'), 3000);
    }) as EventListener);

    // ============================================
    // MODAL INTEGRATION
    // ============================================

    /**
     * Close Alpine modals on HTMX trigger
     */
    document.body.addEventListener('closeModal', () => {
        const modals = document.querySelectorAll('.modal[x-data]');
        modals.forEach((modal) => {
            const modalData = Alpine.$data(modal as HTMLElement) as { open?: boolean; modalOpen?: boolean; close?: () => void } | null;
            if (modalData) {
                // Try common modal state properties
                if (typeof modalData.modalOpen === 'boolean') {
                    modalData.modalOpen = false;
                } else if (typeof modalData.open === 'boolean') {
                    modalData.open = false;
                } else if (typeof modalData.close === 'function') {
                    modalData.close();
                }
            }
        });
    });

    /**
     * Handle modal backdrop cleanup on HTMX swap
     */
    document.body.addEventListener('htmx:beforeSwap', () => {
        // Remove any orphaned modal backdrops
        document.querySelectorAll('.modal-backdrop').forEach(backdrop => {
            backdrop.remove();
        });

        // Reset body scroll if modal was open
        document.body.classList.remove('modal-open');
        document.body.style.overflow = '';
        document.body.style.paddingRight = '';
    });
}

// ============================================
// HELPER FUNCTIONS
// ============================================
// Tooltip functions moved to alpine-tooltip.ts

// ============================================
// EXPORTS
// ============================================

export { initHtmxLifecycle as registerHtmxLifecycle };
export default initHtmxLifecycle;

