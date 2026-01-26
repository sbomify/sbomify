/**
 * Tooltip Manager - Alpine.js Implementation
 * 
 * This file now re-exports the Alpine tooltip functions.
 * The actual implementation is in alpine-tooltip.ts
 */
import { registerAlpineTooltip, initializeTooltipsInContainer, destroyTooltipsInContainer } from './alpine-tooltip';

/**
 * Register Alpine tooltip directive
 * Replaces Bootstrap JS tooltips with Alpine.js
 */
export function registerTooltipManager(): void {
    registerAlpineTooltip();
}

// Re-export functions for HTMX lifecycle
export { initializeTooltipsInContainer, destroyTooltipsInContainer };
