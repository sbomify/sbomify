/**
 * HTMX Lifecycle Handler
 * 
 * Centralized handler for HTMX events, ensuring proper Alpine.js
 * integration, focus management, and state preservation.
 */
import Alpine from 'alpinejs';
import { initTableSorting } from './components/table-sorting';

// Track initialization state
let isInitialized = false;

interface PendingButton {
    element: HTMLButtonElement;
    disabled: boolean;
}

const pendingButtons = new WeakMap<XMLHttpRequest, PendingButton[]>();

/**
 * Initialize all HTMX lifecycle event handlers
 */
export function initHtmxLifecycle(): void {
    if (isInitialized) return;
    isInitialized = true;
    initTableSorting();

    // ============================================
    // HTMX REQUEST LIFECYCLE
    // ============================================

    /**
     * Before HTMX sends a request - add loading states
     */
    document.body.addEventListener('htmx:beforeRequest', ((event: CustomEvent) => {
        const target = event.detail.elt as HTMLElement;

        // Disable submit buttons in the target
        const buttons = Array.from(target.querySelectorAll<HTMLButtonElement>('button[type="submit"]'));
        pendingButtons.set(event.detail.xhr, buttons.map(element => ({ element, disabled: element.disabled })));
        buttons.forEach(button => { button.disabled = true; });
    }) as EventListener);

    /**
     * After HTMX request completes (success or failure)
     */
    document.body.addEventListener('htmx:afterRequest', ((event: CustomEvent) => {
        // Restore button states
        // Restore only the controls this request disabled. A swap may have
        // replaced them with new controls whose state already belongs to Alpine.
        pendingButtons.get(event.detail.xhr)?.forEach(({ element, disabled }) => {
            if (element.isConnected) element.disabled = disabled;
        });
        pendingButtons.delete(event.detail.xhr);
    }) as EventListener);

    // ============================================
    // ALPINE.JS RE-INITIALIZATION AFTER SWAPS
    // ============================================

    /**
     * After HTMX swaps content - reinitialize Alpine components
     * Uses Alpine.morph when available for state preservation
     */
    document.body.addEventListener('htmx:afterSwap', ((event: CustomEvent) => {
        // History restoration emits these events on the restored element
        // without the request-specific detail.target.
        const target = event.detail.target ?? event.target;
        if (!(target instanceof HTMLElement)) return;

        // Find elements with x-data that need initialization
        const alpineElements = target.querySelectorAll('[x-data]');

        alpineElements.forEach((el: Element) => {
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            const htmlEl = el as any;

            // Skip if already initialized by Alpine
            if (htmlEl._x_dataStack) {
                // Element already has Alpine data - use morph if state should persist
                // This is handled automatically by alpine-morph plugin
                return;
            }

            // Initialize new Alpine components
            Alpine.initTree(htmlEl);
        });

    }) as EventListener);

    // ============================================
    // FOCUS MANAGEMENT
    // ============================================

    /**
     * After swap - restore focus to appropriate element
     */
    document.body.addEventListener('htmx:afterSettle', ((event: CustomEvent) => {
        const target = event.detail.target ?? event.target;
        if (!(target instanceof HTMLElement)) return;

        // Look for element with autofocus attribute
        const autofocusEl = target.querySelector<HTMLElement>('[autofocus]');
        if (autofocusEl) {
            autofocusEl.focus();
            return;
        }

        // If a form was *submitted*, focus its first input. afterSettle fires for
        // every swap, including the plain GETs that load a panel on page load, so
        // this has to check the verb: without it, any HTMX-loaded panel containing
        // a form stole focus to its first field the moment the page opened.
        const verb = (event.detail as { requestConfig?: { verb?: string } })?.requestConfig?.verb;
        const wasSubmission = typeof verb === 'string' && verb.toLowerCase() !== 'get';
        if (wasSubmission && (target.tagName === 'FORM' || target.querySelector('form'))) {
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
    }) as EventListener);

    /**
     * Handle HTMX send errors (network failures)
     */
    document.body.addEventListener('htmx:sendError', ((event: CustomEvent) => {
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
    }) as EventListener);
}
