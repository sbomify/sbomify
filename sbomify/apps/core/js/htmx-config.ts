import { getCsrfToken } from './csrf';

export function registerHtmxConfig(): void {
    document.body.addEventListener('htmx:configRequest', (event: Event) => {
        const detail = (event as CustomEvent).detail;
        if (!detail?.headers) {
            return;
        }

        if (detail.headers['X-CSRFToken']) {
            return;
        }

        try {
            detail.headers['X-CSRFToken'] = getCsrfToken();
        } catch {
            // Public views may not include CSRF tokens; avoid breaking the request.
            return;
        }
    });
}
