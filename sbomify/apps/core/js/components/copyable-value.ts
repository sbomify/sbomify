import Alpine from 'alpinejs';

interface CopyableValueParams {
    value: string;
    hideValue: boolean;
    copyFrom: string;
    title: string;
}

/** How long the chip stays in its "copied" state before reverting. */
const COPIED_RESET_MS = 1600;

export function registerCopyableValue() {
    Alpine.data('copyableValue', ({ value, hideValue, copyFrom, title }: CopyableValueParams) => {
        return {
            value,
            hideValue,
            copyFrom,
            title,
            copied: false,
            // Bare timer globals rather than `window.*` so the component is
            // exercisable outside a browser.
            copiedTimer: undefined as ReturnType<typeof setTimeout> | undefined,

            copyToClipboard() {
                const valueToCopy = this.copyFrom
                    ? document.getElementById(this.copyFrom)?.innerText || ''
                    : this.value;

                navigator.clipboard.writeText(valueToCopy).then(() => {
                    // Success is confirmed by the chip itself, not a toast — these
                    // sit in page headers and identifier tables where a toast per
                    // click is far too loud.
                    this.copied = true;
                    clearTimeout(this.copiedTimer);
                    this.copiedTimer = setTimeout(() => {
                        this.copied = false;
                    }, COPIED_RESET_MS);
                }).catch(err => {
                    // A failure is worth interrupting for: the value is not on the
                    // clipboard and the user has no other way to tell.
                    console.error('Failed to copy:', err);
                    this.$dispatch('messages', {
                        value: [{
                            type: 'error',
                            message: 'Failed to copy to clipboard'
                        }]
                    });
                });
            },

            destroy() {
                clearTimeout(this.copiedTimer);
            }
        };
    });
}
