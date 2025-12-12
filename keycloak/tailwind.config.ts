import type { Config } from 'tailwindcss'

/**
 * Tailwind CSS configuration for Keycloak theme
 * Fully self-contained within the keycloak directory
 */
export default {
    content: [
        './themes/sbomify/login/**/*.ftl',
    ],
    theme: {
        extend: {
            colors: {
                // sbomify brand colors (matched to app tokens.css)
                sbomify: {
                    brand: '#3b7ddd',
                    'brand-hover': '#2f64b1',
                    accent: '#7c8b9d',
                    success: '#1cbb8c',
                    danger: '#dc3545',
                    warning: '#fcb92c',
                    // Surface colors
                    surface: '#f9fbfd',
                    'surface-2': '#ffffff',
                    'surface-dark': '#0f172a',
                    'surface-card': 'rgba(15, 23, 42, 0.95)',
                    contrast: '#f8fafc',
                    muted: '#94a3b8',
                    'text-title': '#f8fafc',
                    border: 'rgba(255, 255, 255, 0.1)',
                },
            },
            fontFamily: {
                sans: ['Inter', 'Helvetica Neue', 'Arial', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Roboto', 'sans-serif'],
            },
            borderRadius: {
                'xl': '10px',
                '2xl': '16px',
                '3xl': '20px',
            },
            boxShadow: {
                'card': '0 24px 48px rgba(0, 0, 0, 0.4), inset 0 1px 0 rgba(255, 255, 255, 0.05)',
                'button': '0 8px 20px rgba(59, 125, 221, 0.35)',
                'button-hover': '0 12px 28px rgba(59, 125, 221, 0.45)',
            },
        },
    },
    plugins: [],
} satisfies Config

