/**
 * HTMX Configuration
 * 
 * Global Setup File
 * 
 * This file sets up application-wide HTMX configuration that persists for the
 * lifetime of the application. The event listener is intentionally global and
 * does not require cleanup.
 * 
 * Global setup files vs Component-scoped:
 * - Global: Application-wide, persists for app lifetime, no cleanup needed
 * - Component-scoped: Per-component, requires destroy() cleanup
 */

import { getCsrfToken } from './csrf';

export function registerHtmxConfig(): void {
    document.body.addEventListener('htmx:configRequest', (event: Event) => {
        const detail = (event as CustomEvent).detail;
        if (!detail?.headers) {
            detail.headers = {};
        }

        // Remove any incorrect case versions of the CSRF header (e.g., lowercase from hx-headers)
        const headerKeys = Object.keys(detail.headers);
        for (const key of headerKeys) {
            if (key.toLowerCase() === 'x-csrftoken' && key !== 'X-CSRFToken') {
                delete detail.headers[key];
            }
        }

        // Always set the correct header name with proper case
        // This ensures we override any lowercase versions from hx-headers attribute
        try {
            const token = getCsrfToken();
            if (token && token.trim().length > 0) {
                detail.headers['X-CSRFToken'] = token;
            }
        } catch {
            // Public views may not include CSRF tokens; avoid breaking the request.
            return;
        }
    });
}
