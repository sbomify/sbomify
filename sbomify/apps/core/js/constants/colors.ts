/**
 * Color constants for TypeScript/JavaScript usage
 *
 * IMPORTANT: These must stay synchronized with CSS variables in:
 * - sbomify/assets/css/tailwind.src.css
 *
 * For CSS, always use CSS variables.
 * Only import these constants when dynamically generating colors in JS
 * (e.g., Chart.js configurations, canvas rendering).
 */

/**
 * Barcode rendering colors
 * Note: Must remain pure black/white for barcode scanner compatibility
 */
export const barcodeColors = {
  background: '#FFFFFF',
  foreground: '#000000',
} as const;

/**
 * Default brand colors for team customization fallbacks
 * Must stay synchronized with sbomify/apps/teams/branding.py
 */
export const defaultBrandColors = {
  primary: '#25293F',    // Brand navy ink (matches --color-primary: 37 41 63)
  accent: '#4263EB',     // Brand blue accent
} as const;
