import type htmx from 'htmx.org';
import { getCsrfToken } from './csrf';
import { registerMorphPreserve } from './htmx-morph-preserve';

export function registerHtmxConfig(): void {
    // Every entry point that loads HTMX needs the same swap styles. Registering
    // morph-preserve here rather than in one bundle is what keeps a page from
    // naming an extension its own bundle never defined: htmx silently falls back
    // to defaultSwapStyle, so `hx-swap="morph"` becomes an innerHTML swap.
    registerMorphPreserve();

    // Alpine owns inline visibility and positioning. HTMX's settle phase must
    // not replace those live styles with the incoming HTML's resting state.
    const engine = (window as Window & { htmx?: typeof htmx }).htmx;
    if (engine) {
        engine.config.attributesToSettle = engine.config.attributesToSettle.filter(attribute => attribute !== 'style');
    }

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
