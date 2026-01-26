import Alpine from 'alpinejs';


/**
 * Modal Focus Manager
 * 
 * Global Setup File
 * 
 * This file sets up application-wide modal focus management that persists for the
 * lifetime of the application. Event listeners are intentionally global and
 * do not require cleanup.
 * 
 * Global setup files vs Component-scoped:
 * - Global: Application-wide, persists for app lifetime, no cleanup needed
 * - Component-scoped: Per-component, requires destroy() cleanup
 * 
 * Handles focus management for Bootstrap modals with Alpine.js
 * 
 * Fixes accessibility issue: Ensures focus is removed from modal elements
 * before Bootstrap sets aria-hidden="true" to prevent accessibility violations.
 */
export function registerModalFocusManager(): void {
    /**
     * Global handler to remove focus from modal elements before they're hidden
     * This prevents the accessibility violation where aria-hidden is set on a modal
     * that contains a focused element.
     * 
     * The hide.bs.modal event fires BEFORE Bootstrap sets aria-hidden="true",
     * so we can safely remove focus here.
     */
    const handleModalHide = (event: Event) => {
        const modal = event.target as HTMLElement;
        if (!modal || !modal.classList.contains('modal')) return;

        // Check if the currently focused element is inside this modal
        const activeElement = document.activeElement as HTMLElement;
        if (activeElement && modal.contains(activeElement)) {
            // Remove focus from the element before modal is hidden
            // This prevents the aria-hidden accessibility violation
            // See: https://w3c.github.io/aria/#aria-hidden
            try {
                activeElement.blur();
            } catch (e) {
                // Some elements might not be blurrable, ignore
                console.debug('Could not blur element:', e);
            }
        }
    };

    // Set up global hide handler for all modals (using capture phase to catch early)
    document.body.addEventListener('hide.bs.modal', handleModalHide, true);

    // Set up focus handlers for all modals (fallback for modals without Alpine)
    document.querySelectorAll('.modal').forEach(modalElement => {
        const modal = modalElement as HTMLElement;

        // Skip if already has Alpine data
        if (modal.hasAttribute('x-data')) {
            return;
        }

        modal.addEventListener('shown.bs.modal', () => {
            // Focus first text input in modal
            const input = modal.querySelector('input[type="text"], input[type="email"], textarea, select') as HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement;
            if (input) {
                setTimeout(() => {
                    input.focus();
                    if (input instanceof HTMLInputElement && input.type === 'text') {
                        input.select();
                    }
                }, 50);
            }
        });
    });

    // Also handle dynamically added modals via HTMX
    document.body.addEventListener('htmx:afterSwap', ((event: CustomEvent) => {
        const target = event.detail.target as HTMLElement;
        const modals = target.querySelectorAll('.modal');

        modals.forEach(modalElement => {
            const modal = modalElement as HTMLElement;

            // Skip if already has Alpine data
            if (modal.hasAttribute('x-data')) {
                return;
            }

            modal.addEventListener('shown.bs.modal', () => {
                const input = modal.querySelector('input[type="text"], input[type="email"], textarea, select') as HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement;
                if (input) {
                    setTimeout(() => {
                        input.focus();
                        if (input instanceof HTMLInputElement && input.type === 'text') {
                            input.select();
                        }
                    }, 50);
                }
            });

            // The global hide.bs.modal handler will automatically handle focus removal
            // for dynamically added modals as well
        });
    }) as EventListener);

    // Alpine component for form modal with autofocus
    Alpine.data('formModal', (autofocus: boolean = true) => {
        return {
            open: false,
            autofocus,

            handleShown() {
                if (this.autofocus) {
                    // Focus first input in modal
                    const firstInput = this.$el.querySelector('input[type="text"], input[type="email"], textarea, select') as HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement;
                    if (firstInput) {
                        setTimeout(() => {
                            firstInput.focus();
                            if (firstInput instanceof HTMLInputElement && firstInput.type === 'text') {
                                firstInput.select();
                            }
                        }, 50);
                    }
                }
            }
        };
    });
}
