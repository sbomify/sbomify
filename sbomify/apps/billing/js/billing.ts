import { showSuccess, showError } from '../../core/js/alerts';

// Initialize billing notifications
document.addEventListener('DOMContentLoaded', () => {
    // Check for flash messages in the DOM
    const messages = document.querySelectorAll('[data-flash-message]');
    messages.forEach(messageElement => {
        const message = messageElement.textContent;
        const type = messageElement.getAttribute('data-message-type');

        if (type === 'error') {
            showError(message || '');
        } else {
            showSuccess(message || '');
        }

        // Remove the message element
        messageElement.remove();
    });
});