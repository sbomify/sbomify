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
 * Severity level colors for vulnerability charts and badges
 */
export const severityColors = {
  critical: '#DC3545',  // --color-severity-critical
  high: '#FD7E14',      // --color-severity-high
  medium: '#FFC107',    // --color-severity-medium
  low: '#0DCAF0',       // --color-severity-low
} as const;

/**
 * Provider/source colors for charts
 */
export const providerColors = {
  osv: '#4285F4',              // --color-provider-osv (Google Blue)
  dependencyTrack: '#10B981',  // --color-provider-dependency-track
  default: '#6C757D',          // --color-provider-default
} as const;

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
  primary: '#4F66DC',    // App primary blue (matches --color-primary: 79 102 220)
  accent: '#4F66DC',     // App primary blue
} as const;

/**
 * Helper to convert hex to rgba string
 */
export function hexToRgba(hex: string, alpha: number): string {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}
