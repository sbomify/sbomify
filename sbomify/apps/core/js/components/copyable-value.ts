import Alpine from 'alpinejs';

interface CopyableValueParams {
    value: string;
    hideValue: boolean;
    copyFrom: string;
    title: string;
}

export function registerCopyableValue(): void {
    Alpine.data('copyableValue', ({ value, hideValue, copyFrom, title }: CopyableValueParams) => {
        return {
            value,
            hideValue,
            copyFrom,
            title,

            copyToClipboard() {
                let valueToCopy = this.value;
                
                if (this.copyFrom) {
                    // Try x-ref first (if element is within component scope)
                    const refElement = (this.$refs as { [key: string]: HTMLElement })[this.copyFrom];
                    if (refElement) {
                        valueToCopy = refElement.innerText || refElement.textContent || '';
                    } else {
                        // Fallback to getElementById for elements outside component scope
                        const element = document.getElementById(this.copyFrom);
                        valueToCopy = element?.innerText || element?.textContent || '';
                    }
                }

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
