import Alpine from 'alpinejs';

/**
 * Turnstile Component
 * Handles Cloudflare Turnstile callback functions using Alpine.js
 * 
 * Note: Turnstile requires global callback functions, so we store component references
 * and route callbacks to the appropriate component instance.
 */
const turnstileInstances = new Map<HTMLElement, { tokenInput?: HTMLInputElement }>();

declare global {
    interface Window {
        turnstileCallback?: (token: string) => void;
        turnstileErrorCallback?: () => void;
    }
}

export function registerTurnstile(): void {
    // Set up global callbacks once (shared across all instances)
    if (!window.turnstileCallback) {
        window.turnstileCallback = (token: string) => {
            // Find the most recent/active Turnstile instance
            // In practice, there's usually only one per page
            for (const instance of turnstileInstances.values()) {
                if (instance.tokenInput) {
                    instance.tokenInput.value = token;
                    break; // Update first matching instance
                }
            }
        };

        window.turnstileErrorCallback = () => {
            for (const instance of turnstileInstances.values()) {
                if (instance.tokenInput) {
                    instance.tokenInput.value = '';
                    break;
                }
            }
            console.error('Turnstile error occurred');
        };
    }

    Alpine.data('turnstile', () => {
        return {
            init() {
                // Store reference to this component instance
                const tokenInput = (this.$refs as { tokenInput?: HTMLInputElement }).tokenInput;
                turnstileInstances.set(this.$el, { tokenInput });
            },

            destroy() {
                // Cleanup instance reference
                turnstileInstances.delete(this.$el);
            }
        };
    });
}
