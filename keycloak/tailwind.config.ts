import type { Config } from 'tailwindcss'

/**
 * Tailwind CSS configuration for the Keycloak theme.
 *
 * Self-contained within the keycloak directory: Keycloak serves these pages
 * from its own origin, so it cannot share the app's build.
 *
 * There is deliberately no theme.extend here. Colour, radius, shadow and type
 * come from the design tokens in sbomify.src.css, which mirror the app's
 * tokens. Adding a palette here would be a second source of truth that drifts.
 */
export default {
    content: [
        './themes/sbomify/login/**/*.ftl',
    ],
    plugins: [],
} satisfies Config
