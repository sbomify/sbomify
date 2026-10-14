/**
 * Clipboard utility functions for copying text to clipboard.
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
