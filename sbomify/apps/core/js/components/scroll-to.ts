import Alpine from 'alpinejs';

/**
 * Scroll To Utility Component
 * Provides smooth scrolling functionality using Alpine.js patterns
 * 
 * Usage in templates:
 *   @click="$dispatch('scroll-to', { id: 'elementId', block: 'start', behavior: 'smooth' })"
 * 
 * Or use the scrollTo method directly:
 *   scrollTo('elementId', { block: 'start', behavior: 'smooth' })
 */

interface ScrollToOptions {
    block?: ScrollLogicalPosition;
    behavior?: ScrollBehavior;
    inline?: ScrollLogicalPosition;
}

/**
 * Scroll to an element by ID or element reference
 */
export function scrollTo(
    target: string | HTMLElement,
    options: ScrollToOptions = { behavior: 'smooth', block: 'start' }
): void {
    let element: HTMLElement | null = null;

    if (typeof target === 'string') {
        element = document.getElementById(target) || document.querySelector(target) as HTMLElement;
    } else {
        element = target;
    }

    if (!element) {
        console.warn(`[scrollTo] Element not found: ${target}`);
        return;
    }

    // Use $nextTick if available (Alpine context), otherwise use setTimeout
    const scroll = () => {
        element!.scrollIntoView({
            behavior: options.behavior || 'smooth',
            block: options.block || 'start',
            inline: options.inline || 'nearest'
        });
    };

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    if (window.Alpine && (window.Alpine as any).nextTick) {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        (window.Alpine as any).nextTick(scroll);
    } else {
        setTimeout(scroll, 0);
    }
}

// Global event listener reference for cleanup
let scrollToEventListener: ((event: Event) => void) | null = null;

/**
 * Event handler for scroll-to events
 */
function handleScrollToEvent(event: Event): void {
    const customEvent = event as CustomEvent;
    const { id, block = 'start', behavior = 'smooth', inline = 'nearest' } = customEvent.detail || {};

    if (!id) {
        console.warn('[scrollTo] No element ID provided in scroll-to event');
        return;
    }

    scrollTo(id, { block, behavior, inline });
}

/**
 * Register Alpine component for scroll-to functionality
 * Listens for 'scroll-to' events and scrolls to target element
 * 
 * NOTE: This adds a global event listener to document.body. Use cleanupScrollTo()
 * to remove it if needed (typically not needed as it's application-wide).
 */
export function registerScrollTo(): void {
    // Only register once
    if (scrollToEventListener) {
        return;
    }

    // Global event listener for scroll-to events
    scrollToEventListener = handleScrollToEvent as (event: Event) => void;
    document.body.addEventListener('scroll-to', scrollToEventListener);

    // Register as Alpine data component for direct use
    Alpine.data('scrollTo', (target: string | HTMLElement, options?: ScrollToOptions) => {
        return {
            target,
            options: options || { behavior: 'smooth', block: 'start' },

            scroll() {
                scrollTo(this.target, this.options as ScrollToOptions);
            }
        };
    });
}

/**
 * Cleanup function to remove the global scroll-to event listener
 * Typically not needed as the listener is application-wide, but available
 * for cases where scroll-to functionality needs to be disabled.
 */
export function cleanupScrollTo(): void {
    if (scrollToEventListener) {
        document.body.removeEventListener('scroll-to', scrollToEventListener);
        scrollToEventListener = null;
    }
}
