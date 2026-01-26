/**
 * Clipboard Global Initialization
 * 
 * Global Setup File
 * 
 * This file sets up application-wide clipboard button initialization that persists
 * for the lifetime of the application. The event listener is intentionally global
 * and does not require cleanup.
 * 
 * Global setup files vs Component-scoped:
 * - Global: Application-wide, persists for app lifetime, no cleanup needed
 * - Component-scoped: Per-component, requires destroy() cleanup
 * 
 * Clipboard functions are now available via Alpine stores ($store.clipboard.*)
 * Import directly for use in non-Alpine contexts
 */
import { copyToClipboard, initCopyButtons } from './clipboard';

// Note: Button initialization is now handled by Alpine.js clipboardButton component
// Re-initialize after HTMX content swaps (fallback for buttons without Alpine)
document.body.addEventListener('htmx:afterSwap', (event) => {
  const target = (event as CustomEvent).detail?.target;
  if (target instanceof HTMLElement) {
    // Only initialize buttons that don't have Alpine x-data
    const buttonsWithoutAlpine = target.querySelectorAll<HTMLElement>('[data-copy-value]:not([x-data]), [data-public-url]:not([x-data])');
    if (buttonsWithoutAlpine.length > 0) {
      initCopyButtons(target);
    }
  }
});

export { copyToClipboard, initCopyButtons };
