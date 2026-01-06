export function getCsrfToken(): string {
    const token = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content');
    if (token) {
        return token;
    }

    const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    const cookieValue = match?.[1];
    
    if (!cookieValue) {
        throw new Error('CSRF token not found in meta tag or cookies. Ensure CSRF middleware is enabled.');
    }
    
    return decodeURIComponent(cookieValue);
}

