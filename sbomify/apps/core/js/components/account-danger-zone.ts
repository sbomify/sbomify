import { showError } from '../alerts-global';

interface AccountDangerZoneConfig {
    csrfToken: string;
}

export function registerAccountDangerZone() {
    if (window.Alpine) {
        window.Alpine.data('accountDangerZone', (config: AccountDangerZoneConfig) => ({
            isExpanded: false,
            showDeleteModal: false,
            confirmText: '',
            isDeleting: false,
            validationError: null as string | null,
            csrfToken: config.csrfToken,

            get canConfirm(): boolean {
                return this.confirmText.toLowerCase() === 'delete';
            },

            toggle(): void {
                this.isExpanded = !this.isExpanded;
            },

            openDeleteModal(): void {
                this.showDeleteModal = true;
                this.validationError = null;
            },

            closeModal(): void {
                this.showDeleteModal = false;
                this.confirmText = '';
                this.validationError = null;
            },

            async deleteAccount(): Promise<void> {
                if (!this.canConfirm || this.isDeleting) return;

                this.isDeleting = true;
                this.validationError = null;

                try {
                    const response = await fetch('/api/v1/user/delete', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-CSRFToken': this.csrfToken,
                        },
                        body: JSON.stringify({ confirmation: this.confirmText }),
                    });

                    const data = await response.json();

                    if (response.ok) {
                        window.location.href = '/login/';
                    } else {
                        this.validationError = data.detail || 'An error occurred while deleting your account.';
                    }
                } catch (error) {
                    console.error('Account deletion failed:', error);
                    this.validationError = 'A network error occurred. Please try again.';
                    showError('A network error occurred. Please try again.');
                } finally {
                    this.isDeleting = false;
                }
            },
        }));
    }
}
