import Alpine from 'alpinejs';

/**
 * Token Form Component
 * Handles token generation form reset and success message display
 */
export function registerTokenForm(): void {
    Alpine.data('tokenForm', () => {
        return {
            init() {
                // Check if there's a new token to show success message
                const tokenElement = document.getElementById('access-token');
                if (tokenElement) {
                    // Use alerts store
                    try {
                        (this as { $store: { alerts?: { showSuccess: (message: string) => void } } }).$store.alerts?.showSuccess('Personal access token created successfully!');
                    } catch {
                        // Fallback if store not available
                        console.log('Token created successfully');
                    }
                }
            },

            resetForm() {
                const form = (this.$refs as { form?: HTMLFormElement }).form;
                if (form) {
                    form.reset();
                }
            }
        };
    });
}
