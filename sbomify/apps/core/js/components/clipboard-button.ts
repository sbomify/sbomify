import Alpine from 'alpinejs';
import { copyToClipboard } from '../clipboard';

/**
 * Clipboard Button Component
 * Handles copy buttons with data-copy-value or data-public-url attributes
 */
export function registerClipboardButton(): void {
    Alpine.data('clipboardButton', () => {
        return {
            async handleClick(event: Event) {
                event.preventDefault();
                
                const button = event.currentTarget as HTMLElement;
                const copyValue = button.dataset.copyValue;
                const publicUrl = button.dataset.publicUrl;
                
                if (copyValue) {
                    await copyToClipboard(copyValue);
                } else if (publicUrl) {
                    await copyToClipboard(publicUrl, 'Public URL copied to clipboard', 'Failed to copy URL to clipboard');
                }
            }
        };
    });
}
