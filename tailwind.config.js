import flowbite from 'flowbite/plugin'

/** @type {import('tailwindcss').Config} */
export default {
  prefix: 'tw-',
  content: [
    './sbomify/apps/**/templates/**/*.{html,html.j2,j2}',
    './sbomify/apps/**/js/**/*.{js,ts}',
    './node_modules/flowbite/**/*.js',
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        // Brand Primary Colors
        navy: {
          DEFAULT: '#0F0F2D',
          light: '#1A1A3E',
        },
        purple: {
          DEFAULT: '#7B7A9E',
          light: '#C8C5D8',
        },
        // Brand Accent Colors
        primary: {
          DEFAULT: 'rgb(var(--color-primary) / <alpha-value>)',
          dark: 'rgb(var(--color-primary-dark) / <alpha-value>)',
          blue: '#4059D0',
          pink: '#CC58BB',
          peach: '#F4B57F',
        },
        // Semantic Colors (using CSS variables for theming)
        surface: {
          DEFAULT: 'rgb(var(--color-surface) / <alpha-value>)',
          dark: '#1A1A3E',
          light: '#ffffff',
        },
        background: {
          DEFAULT: 'rgb(var(--color-background) / <alpha-value>)',
          dark: '#0F0F2D',
          light: '#f8fafc',
        },
        border: {
          DEFAULT: 'rgb(var(--color-border) / <alpha-value>)',
          dark: '#2D2D4A',
          light: '#e2e8f0',
        },
        text: {
          DEFAULT: 'rgb(var(--color-text) / <alpha-value>)',
          muted: 'rgb(var(--color-text-muted) / <alpha-value>)',
        },
        success: 'rgb(var(--color-success) / <alpha-value>)',
        warning: 'rgb(var(--color-warning) / <alpha-value>)',
        danger: 'rgb(var(--color-danger) / <alpha-value>)',
      },
      fontFamily: {
        display: ['Agrandir', 'system-ui', 'sans-serif'],
        sans: ['Inter', 'system-ui', 'sans-serif'],
      },
      backgroundImage: {
        'brand-gradient': 'linear-gradient(90deg, #4059D0 0%, #CC58BB 50%, #F4B57F 100%)',
      },
      boxShadow: {
        'card': '0 1px 3px 0 rgb(0 0 0 / 0.1), 0 1px 2px -1px rgb(0 0 0 / 0.1)',
        'card-hover': '0 4px 6px -1px rgb(0 0 0 / 0.1), 0 2px 4px -2px rgb(0 0 0 / 0.1)',
      },
      animation: {
        'fade-in': 'fadeIn 0.3s ease-out',
        'fade-in-up': 'fadeInUp 0.4s ease-out',
        'slide-in-left': 'slideInLeft 0.3s ease-out',
        'slide-in-right': 'slideInRight 0.3s ease-out',
      },
      keyframes: {
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        fadeInUp: {
          '0%': { opacity: '0', transform: 'translateY(10px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        slideInLeft: {
          '0%': { opacity: '0', transform: 'translateX(-20px)' },
          '100%': { opacity: '1', transform: 'translateX(0)' },
        },
        slideInRight: {
          '0%': { opacity: '0', transform: 'translateX(20px)' },
          '100%': { opacity: '1', transform: 'translateX(0)' },
        },
      },
    },
  },
  plugins: [flowbite],
}
