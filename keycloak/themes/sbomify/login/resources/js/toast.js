/**
 * Toast notification functionality for Keycloak theme
 * Displays success messages as toast notifications
 */
(function() {
    'use strict';

    /**
     * Creates and displays a toast notification
     * @param {string} message - The message to display (already sanitized)
     */
    function showToast(message) {
        if (!message || typeof message !== 'string') {
            return;
        }

        // Create toast container
        const toast = document.createElement('div');
        toast.className = 'toast-banner';
        toast.setAttribute('role', 'alert');
        toast.setAttribute('aria-live', 'polite');

        // Create toast content structure
        const toastContent = document.createElement('div');
        toastContent.className = 'toast-content';

        // Create SVG icon
        const iconSvg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        iconSvg.setAttribute('class', 'toast-icon');
        iconSvg.setAttribute('width', '20');
        iconSvg.setAttribute('height', '20');
        iconSvg.setAttribute('viewBox', '0 0 24 24');
        iconSvg.setAttribute('fill', 'none');
        iconSvg.setAttribute('stroke', 'currentColor');
        iconSvg.setAttribute('stroke-width', '2');
        iconSvg.setAttribute('aria-hidden', 'true');

        const path1 = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        path1.setAttribute('d', 'M22 11.08V12a10 10 0 1 1-5.93-9.14');

        const polyline = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
        polyline.setAttribute('points', '22 4 12 14.01 9 11.01');

        iconSvg.appendChild(path1);
        iconSvg.appendChild(polyline);

        // Create message span
        const messageSpan = document.createElement('span');
        messageSpan.className = 'toast-message';
        messageSpan.textContent = message; // Use textContent for XSS protection

        // Assemble structure
        toastContent.appendChild(iconSvg);
        toastContent.appendChild(messageSpan);
        toast.appendChild(toastContent);

        // Append to body
        document.body.appendChild(toast);

        // Trigger animation
        requestAnimationFrame(function() {
            toast.classList.add('show');
        });

        // Auto-hide after 2 seconds
        setTimeout(function() {
            toast.classList.remove('show');
            setTimeout(function() {
                if (toast.parentNode) {
                    toast.remove();
                }
            }, 300); // Wait for transition to complete
        }, 2000);
    }

    /**
     * Initialize toast on page load
     */
    function initToast() {
        // Check if there's a data attribute with the message
        const toastData = document.querySelector('[data-toast-message]');
        if (toastData) {
            const message = toastData.getAttribute('data-toast-message');
            if (message) {
                showToast(message);
            }
        }
    }

    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initToast);
    } else {
        initToast();
    }
})();
