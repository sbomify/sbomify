/**
 * Clipboard utility functions for copying text to clipboard.
 * These are exposed globally via clipboard-global.ts
 */

import { showSuccess, showError } from './alerts';

/**
 * Copy text to clipboard and show a success/error notification.
 *
 * @param text - The text to copy to clipboard
 * @param successMessage - Optional custom success message (default: "Copied to clipboard")
 * @param errorMessage - Optional custom error message (default: "Failed to copy to clipboard")
 * @returns Promise<boolean> - true if copy succeeded, false otherwise
 */
export async function copyToClipboard(
  text: string,
  successMessage: string = 'Copied to clipboard',
  errorMessage: string = 'Failed to copy to clipboard'
): Promise<boolean> {
  if (!text) {
    showError(errorMessage);
    return false;
  }

  try {
    await navigator.clipboard.writeText(text);
    showSuccess(successMessage);
    return true;
  } catch (err) {
    console.error('Failed to copy to clipboard:', err);
    showError(errorMessage);
    return false;
  }
}

/**
 * Initialize copy buttons on the page.
 * Looks for elements with [data-copy-value] or [data-public-url] attributes.
 *
 * Usage:
 *   <button data-copy-value="text to copy">Copy</button>
 *   <button data-public-url="https://example.com">Copy URL</button>
 */
export function initCopyButtons(container: HTMLElement | Document = document): void {
  // Handle data-copy-value buttons
  container.querySelectorAll<HTMLElement>('[data-copy-value]').forEach((btn) => {
    btn.addEventListener('click', async (event) => {
      event.preventDefault();
      const value = btn.dataset.copyValue;
      if (value) {
        await copyToClipboard(value);
      }
    });
  });

  // Handle data-public-url buttons (for "Copy public URL" functionality)
  container.querySelectorAll<HTMLElement>('[data-public-url]').forEach((btn) => {
    btn.addEventListener('click', async (event) => {
      event.preventDefault();
      const url = btn.dataset.publicUrl;
      if (url) {
        await copyToClipboard(url, 'Public URL copied to clipboard', 'Failed to copy URL to clipboard');
      }
    });
  });
}
