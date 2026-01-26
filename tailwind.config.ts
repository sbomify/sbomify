/**
 * Tailwind CSS Configuration
 * 
 * Tailwind CSS 4.0 supports automatic content detection, but explicit
 * configuration is recommended for reliability and performance.
 * 
 * This config maps existing design tokens from tokens.css to Tailwind
 * theme extensions, allowing use of CSS variables in Tailwind classes.
 * 
 * Note: Tailwind 4.0 uses CSS-first configuration, but this JS config
 * is still supported for migration and explicit content paths.
 */
const config = {
  content: [
    './sbomify/apps/**/templates/**/*.{html,j2}',
    './sbomify/templates/**/*.{html,j2}',
    './sbomify/apps/**/js/**/*.{ts,js}',
  ],
  theme: {
    extend: {
      colors: {
        // Brand colors from design tokens
        brand: {
          primary: 'var(--brand-primary)',
          secondary: 'var(--brand-secondary)',
          success: 'var(--brand-success)',
          danger: 'var(--brand-danger)',
          warning: 'var(--brand-warning)',
          info: 'var(--brand-info)',
        },
        // Status color scales (Tailwind-compatible)
        success: {
          50: 'var(--success-50)',
          100: 'var(--success-100)',
          200: 'var(--success-200)',
          300: 'var(--success-300)',
          400: 'var(--success-400)',
          500: 'var(--success-500)',
          600: 'var(--success-600)',
          700: 'var(--success-700)',
          800: 'var(--success-800)',
          900: 'var(--success-900)',
        },
        danger: {
          50: 'var(--danger-50)',
          100: 'var(--danger-100)',
          200: 'var(--danger-200)',
          300: 'var(--danger-300)',
          400: 'var(--danger-400)',
          500: 'var(--danger-500)',
          600: 'var(--danger-600)',
          700: 'var(--danger-700)',
          800: 'var(--danger-800)',
          900: 'var(--danger-900)',
        },
        warning: {
          50: 'var(--warning-50)',
          100: 'var(--warning-100)',
          200: 'var(--warning-200)',
          300: 'var(--warning-300)',
          400: 'var(--warning-400)',
          500: 'var(--warning-500)',
          600: 'var(--warning-600)',
          700: 'var(--warning-700)',
          800: 'var(--warning-800)',
          900: 'var(--warning-900)',
        },
        info: {
          50: 'var(--info-50)',
          100: 'var(--info-100)',
          200: 'var(--info-200)',
          300: 'var(--info-300)',
          400: 'var(--info-400)',
          500: 'var(--info-500)',
          600: 'var(--info-600)',
          700: 'var(--info-700)',
          800: 'var(--info-800)',
          900: 'var(--info-900)',
        },
        // Neutral grays
        gray: {
          50: 'var(--gray-50)',
          100: 'var(--gray-100)',
          200: 'var(--gray-200)',
          300: 'var(--gray-300)',
          400: 'var(--gray-400)',
          500: 'var(--gray-500)',
          600: 'var(--gray-600)',
          700: 'var(--gray-700)',
          800: 'var(--gray-800)',
          900: 'var(--gray-900)',
        },
        // Semantic text colors
        text: {
          primary: 'var(--text-primary)',
          secondary: 'var(--text-secondary)',
          muted: 'var(--text-muted)',
          title: 'var(--text-title)',
          link: 'var(--text-link)',
          'link-hover': 'var(--text-link-hover)',
          inverse: 'var(--text-inverse)',
        },
        // Background colors
        bg: {
          primary: 'var(--bg-primary)',
          secondary: 'var(--bg-secondary)',
          tertiary: 'var(--bg-tertiary)',
          glass: 'var(--bg-glass)',
        },
        // Surface colors
        surface: {
          card: 'var(--surface-card)',
          'card-muted': 'var(--surface-card-muted)',
          border: 'var(--surface-border)',
          dark: 'var(--surface-dark)',
          'muted-alt': 'var(--surface-muted-alt)',
        },
      },
      fontFamily: {
        primary: ['var(--font-family-primary)', 'sans-serif'],
        brand: ['var(--font-family-brand)', 'sans-serif'],
        mono: ['var(--font-family-mono)', 'monospace'],
      },
      fontSize: {
        xs: 'var(--font-size-xs)',
        sm: 'var(--font-size-sm)',
        base: 'var(--font-size-base)',
        lg: 'var(--font-size-lg)',
        xl: 'var(--font-size-xl)',
        '2xl': 'var(--font-size-2xl)',
        '3xl': 'var(--font-size-3xl)',
      },
      fontWeight: {
        normal: 'var(--font-weight-normal)',
        medium: 'var(--font-weight-medium)',
        semibold: 'var(--font-weight-semibold)',
        bold: 'var(--font-weight-bold)',
      },
      lineHeight: {
        normal: 'var(--line-height-normal)',
        tight: 'var(--line-height-tight)',
        relaxed: 'var(--line-height-relaxed)',
      },
      spacing: {
        xs: 'var(--spacing-xs)',
        sm: 'var(--spacing-sm)',
        md: 'var(--spacing-md)',
        lg: 'var(--spacing-lg)',
        xl: 'var(--spacing-xl)',
        '2xl': 'var(--spacing-2xl)',
      },
      borderRadius: {
        sm: 'var(--radius-sm)',
        md: 'var(--radius-md)',
        lg: 'var(--radius-lg)',
        xl: 'var(--radius-xl)',
        full: 'var(--radius-full)',
      },
      boxShadow: {
        sm: 'var(--shadow-sm)',
        md: 'var(--shadow-md)',
        lg: 'var(--shadow-lg)',
        card: 'var(--shadow-card)',
      },
      zIndex: {
        dropdown: 'var(--z-dropdown)',
        sticky: 'var(--z-sticky)',
        fixed: 'var(--z-fixed)',
        'modal-backdrop': 'var(--z-modal-backdrop)',
        modal: 'var(--z-modal)',
        popover: 'var(--z-popover)',
        tooltip: 'var(--z-tooltip)',
      },
      transitionProperty: {
        base: 'var(--transition-base)',
        fast: 'var(--transition-fast)',
        smooth: 'var(--transition-smooth)',
      },
    },
  },
  plugins: [],
}

export default config
