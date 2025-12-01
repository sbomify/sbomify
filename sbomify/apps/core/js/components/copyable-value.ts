import Alpine from 'alpinejs';

interface CopyableValueParams {
    value: string;
    hideValue: boolean;
    copyFrom: string;
    title: string;
}

export function registerCopyableValue() {
    Alpine.data('copyableValue', ({ value, hideValue, copyFrom, title }: CopyableValueParams) => {
        return {
            value,
            hideValue,
            copyFrom,
            title,

            copyToClipboard() {
                const valueToCopy = this.copyFrom
                    ? document.getElementById(this.copyFrom)?.innerText || ''
                    : this.value;

                navigator.clipboard.writeText(valueToCopy).then(() => {
                    this.$dispatch('messages', {
                        value: [{
                            type: 'success',
                            message: 'Copied to clipboard'
                        }]
                    });
                }).catch(err => {
                    console.error('Failed to copy:', err);
                    this.$dispatch('messages', {
                        value: [{
                            type: 'error',
                            message: 'Failed to copy to clipboard'
                        }]
                    });
                });
            }
        };
    });
}
