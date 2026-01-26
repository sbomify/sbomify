import Alpine from 'alpinejs';
import { showSuccess, showError } from '../../core/js/alerts';

/**
 * Flash Messages Component
 * Processes flash messages with data-flash-message attributes and displays them as toasts
 */
export function registerFlashMessages() {
    Alpine.data('flashMessages', () => {
        return {
            init() {
                this.processMessages();
            },
            
            processMessages() {
                // Check for flash messages in the component scope
                const messages = this.$el.querySelectorAll('[data-flash-message]');
                messages.forEach((messageElement) => {
                    const element = messageElement as HTMLElement;
                    const message = element.textContent;
                    const type = element.getAttribute('data-message-type');

                    if (type === 'error') {
                        showError(message || '');
                    } else {
                        showSuccess(message || '');
                    }

                    // Remove the message element
                    element.remove();
                });
            }
        };
    });
}