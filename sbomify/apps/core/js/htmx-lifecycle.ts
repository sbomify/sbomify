/**
 * HTMX Lifecycle Handler
 * 
 * Centralized handler for HTMX events, ensuring proper Alpine.js
 * integration, focus management, and state preservation.
 */
import Alpine from 'alpinejs';

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
     * After HTMX swaps content - reinitialize Alpine components
     * Uses Alpine.morph when available for state preservation
     */
    document.body.addEventListener('htmx:afterSwap', ((event: CustomEvent) => {
        const target = event.detail.target as HTMLElement;

        // Initialize Alpine on new [x-data] elements BEFORE revealing body.
        // For boosted navigations, HTMX merges body attributes from the response,
        // which removes the 'ready' class (opacity: 0). We must process x-show
        // directives first so dropdowns are hidden before the body becomes visible.
        const alpineElements = target.querySelectorAll('[x-data]');

        alpineElements.forEach((el: Element) => {
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            const htmlEl = el as any;

            // Skip if already initialized by Alpine
            if (htmlEl._x_dataStack) {
                return;
            }

            // Initialize new Alpine components
            Alpine.initTree(htmlEl);
        });

        // Now safe to reveal body — Alpine has processed x-show directives
        document.body.classList.add('ready');

    }) as EventListener);

    /**
     * Before HTMX swap - cleanup event listeners and state
     */
    document.body.addEventListener('htmx:beforeSwap', ((event: CustomEvent) => {
        const target = event.detail.target as HTMLElement;

        // Dispatch cleanup event for custom cleanup handlers
        target.dispatchEvent(new CustomEvent('alpine:beforeSwap', { bubbles: true }));
    }) as EventListener);

    // ============================================
    // FOCUS MANAGEMENT
    // ============================================

    /**
     * After swap - restore focus to appropriate element
     * Skip for full-page (hx-boost) swaps where the target is <body>.
     */
    document.body.addEventListener('htmx:afterSettle', ((event: CustomEvent) => {
        const target = event.detail.target as HTMLElement;

        // Skip focus management for full-page boosted navigations —
        // auto-focusing the first input makes no sense after a page navigation.
        if (target === document.body) return;

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

        // Show error toast if available
        if (typeof window.showToast === 'function') {
            window.showToast({
                type: 'error',
                title: 'Request Failed',
                message: `Error ${xhr.status}: ${xhr.statusText || 'An error occurred'}`
            });
        }

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
        if (typeof window.showToast === 'function') {
            window.showToast({
                type: 'error',
                title: 'Network Error',
                message: 'Failed to connect to server. Please check your connection.'
            });
        }

        target.classList.add('htmx-error');
        setTimeout(() => target.classList.remove('htmx-error'), 3000);
    }) as EventListener);

    // ============================================
    // MODAL INTEGRATION
    // ============================================

    /**
     * Close Bootstrap modals on HTMX trigger
     */
    document.body.addEventListener('closeModal', () => {
        // Bootstrap modals have been migrated to Alpine.js
        // This event listener is kept for backward compatibility but is no longer needed
        if (import.meta.env.DEV) {
            console.warn('closeModal event is deprecated - Bootstrap modals have been migrated to Alpine.js');
        }
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
// EXPORTS
// ============================================

export { initHtmxLifecycle as registerHtmxLifecycle };
export default initHtmxLifecycle;

