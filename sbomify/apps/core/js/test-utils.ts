/**
 * Shared test utilities for frontend tests
 */

/**
 * Parse CSRF token from cookie string - test implementation
 * Mirrors the logic used in production CSRF handling
 */
export function parseCsrfFromCookie(cookieString: string): string {
    const match = cookieString.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : '';
}

/**
 * Get CSRF token using priority logic - test implementation
 * Priority: meta tag > cookie
 */
export function getCsrfTokenFromSources(
    metaContent: string | null,
    cookieValue: string | null
): string {
    if (metaContent) return metaContent;
    if (cookieValue) return cookieValue;
    return '';
}

/**
 * Validate CSRF token and return result
 */
export function validateCsrfToken(token: string): { valid: boolean; errorMsg?: string } {
    if (!token || !token.trim()) {
        return {
            valid: false,
            errorMsg: 'Security error: Missing CSRF token. Please reload the page and try again.'
        };
    }
    return { valid: true };
}
