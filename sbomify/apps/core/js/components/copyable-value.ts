import Alpine from 'alpinejs';

interface CopyableValueParams {
    value: string;
    hideValue?: boolean;
    copyFrom?: string;
    copySelector?: string;
    title?: string;
}

/** How long the chip stays in its "copied" state before reverting. */
const COPIED_RESET_MS = 1600;

export function registerCopyableValue() {
    Alpine.data('copyableValue', ({ value, hideValue = false, copyFrom = '', copySelector = '', title = '' }: CopyableValueParams) => {
        return {
            value,
            hideValue,
            copyFrom,
            title,
            copied: false,
            // Bare timer globals rather than `window.*` so the component is
            // exercisable outside a browser.
            copiedTimer: undefined as ReturnType<typeof setTimeout> | undefined,

            async copyToClipboard() {
                const valueToCopy = copySelector
                    ? this.$el.closest('[data-copy-container]')?.querySelector(copySelector)?.textContent || ''
                    : this.copyFrom
                    ? document.getElementById(this.copyFrom)?.innerText || ''
                    : this.value;

                // A selector or id that resolves to nothing would otherwise
                // reach writeText(''), which succeeds: the chip would go green
                // while quietly clearing the clipboard. That is the same false
                // success this component exists to avoid, so an empty value is
                // a failure, exactly as clipboard.ts already treats it.
                if (!valueToCopy) {
                    this.reportFailure(new Error('Nothing to copy'));
                    return;
                }

                try {
                    await navigator.clipboard.writeText(valueToCopy);
                    // Success is confirmed by the chip itself, not a toast — these
                    // sit in page headers and identifier tables where a toast per
                    // click is far too loud.
                    this.copied = true;
                    clearTimeout(this.copiedTimer);
                    this.copiedTimer = setTimeout(() => {
                        this.copied = false;
                    }, COPIED_RESET_MS);
                } catch (err) {
                    this.reportFailure(err);
                }
            },

            // A failure is worth interrupting for: the value is not on the
            // clipboard and the user has no other way to tell.
            reportFailure(err: unknown) {
                console.error('Failed to copy:', err);
                this.$dispatch('messages', {
                    value: [{
                        type: 'error',
                        message: 'Failed to copy to clipboard'
                    }]
                });
            },

            destroy() {
                clearTimeout(this.copiedTimer);
            }
        };
    });
}
