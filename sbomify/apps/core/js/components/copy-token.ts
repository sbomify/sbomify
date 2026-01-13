import Alpine from 'alpinejs';

interface NotificationMethods {
    showSuccess?: (message: string) => void | Promise<unknown>;
    showError?: (message: string) => void | Promise<unknown>;
}

export function registerCopyToken() {
    Alpine.data('copyToken', () => ({
        showCopied: false,

        displayCopiedFor2Seconds() {
            this.showCopied = true;
            setTimeout(() => {
                this.showCopied = false;
            }, 2000);
        },

        copyToken() {
            const tokenElement = document.getElementById('access-token');
            if (!tokenElement) {
                console.error('Token element not found');
                return;
            }

            const token = tokenElement.innerText || tokenElement.textContent || '';

            navigator.clipboard.writeText(token).then(() => {
                this.displayCopiedFor2Seconds();
                const windowWithNotifications = window as unknown as NotificationMethods;
                if (windowWithNotifications.showSuccess) {
                    windowWithNotifications.showSuccess('Token copied to clipboard!');
                }
            }).catch(err => {
                console.error('Failed to copy token:', err);
                this.fallbackCopyToClipboard(token);
            });
        },

        fallbackCopyToClipboard(text: string) {
            const textArea = document.createElement('textarea');
            textArea.value = text;
            textArea.style.position = 'fixed';
            textArea.style.left = '-999999px';
            textArea.style.top = '-999999px';
            document.body.appendChild(textArea);
            textArea.focus();
            textArea.select();

            try {
                document.execCommand('copy');
                this.displayCopiedFor2Seconds();
                const windowWithNotifications = window as unknown as NotificationMethods;
                if (windowWithNotifications.showSuccess) {
                    windowWithNotifications.showSuccess('Token copied to clipboard!');
                }
            } catch (err) {
                console.error('Fallback copy failed:', err);
                const windowWithNotifications = window as unknown as NotificationMethods;
                if (windowWithNotifications.showError) {
                    windowWithNotifications.showError('Failed to copy token. Please copy manually.');
                }
            }

            document.body.removeChild(textArea);
        }
    }));
}
