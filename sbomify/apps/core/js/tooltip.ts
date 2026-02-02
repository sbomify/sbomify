/**
 * This file has been replaced by alpine-tooltip.ts
 * Bootstrap tooltip functionality is no longer used - all tooltips now use Alpine.js
 *
 * See sbomify/apps/core/js/alpine-tooltip.ts for the new implementation
 */

export function registerTooltipDirective() {
  console.warn('registerTooltipDirective from tooltip.ts is deprecated. Use alpine-tooltip.ts instead.');
}

export function registerTooltipManager() {
  console.warn('registerTooltipManager from tooltip.ts is deprecated. Use alpine-tooltip.ts instead.');
}

export function cleanupOrphanedTooltips() {
  // No-op - Bootstrap tooltips are no longer used
}
