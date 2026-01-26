import Alpine from 'alpinejs';

/**
 * Modal Form Handler
 * Handles form submission on Enter key in modals
 */
export function registerModalFormHandler(): void {
    Alpine.data('modalFormHandler', () => {
        return {
            handleKeydown(event: KeyboardEvent) {
                // Handle Enter key submission in modal forms
                if (event.key === 'Enter' && !event.shiftKey) {
                    const activeElement = event.target as HTMLElement;
                    
                    // Don't submit if in textarea
                    if (activeElement.tagName === 'TEXTAREA') {
                        return;
                    }
                    
                    // Check if we're in a modal form
                    const modal = activeElement.closest('.modal') as HTMLElement;
                    if (!modal) return;
                    
                    const form = modal.querySelector('form') as HTMLFormElement;
                    if (!form || !form.contains(activeElement)) return;
                    
                    // Prevent default and submit form
                    event.preventDefault();
                    form.submit();
                }
            }
        };
    });
}
