/**
 * All Releases Table Component - TypeScript functionality
 * Handles creating releases from the releases dashboard page
 */

import { NotificationManager } from '../utils/django-components';

interface CreateReleaseForm {
    product_id: string;
    name: string;
    description: string;
    is_prerelease: boolean;
}

interface CreateReleaseResponse {
    id: string;
    name: string;
    product_id: string;
    message?: string;
}

class AllReleasesTable {
    private modal: { show(): void; hide(): void } | null = null;
    private form: HTMLFormElement | null = null;
    private createBtn: HTMLButtonElement | null = null;
    private spinner: HTMLElement | null = null;
    private errorDiv: HTMLElement | null = null;

    constructor() {
        this.init();
    }

    private init(): void {
        const modalElement = document.getElementById('createReleaseModal');
        if (modalElement) {
            this.modal = new window.bootstrap.Modal(modalElement);
            this.form = modalElement.querySelector('#createReleaseForm');
            this.createBtn = modalElement.querySelector('#createReleaseBtn');
            this.spinner = modalElement.querySelector('#createReleaseSpinner');
            this.errorDiv = modalElement.querySelector('#createReleaseError');

            this.bindEvents();
        }

        // Initialize edit and delete button listeners
        this.initializeEditButtons();
        this.initializeDeleteButtons();
    }

    private bindEvents(): void {
        if (this.createBtn) {
            this.createBtn.addEventListener('click', this.handleCreateRelease.bind(this));
        }

        // Clear form when modal is shown
        const modalElement = document.getElementById('createReleaseModal');
        if (modalElement) {
            modalElement.addEventListener('show.bs.modal', () => {
                this.clearForm();
                this.hideError();
            });
        }
    }

    private async handleCreateRelease(): Promise<void> {
        if (!this.form) return;

        const formData = new FormData(this.form);
        const data: CreateReleaseForm = {
            product_id: formData.get('product_id') as string,
            name: formData.get('name') as string,
            description: formData.get('description') as string || '',
            is_prerelease: formData.get('is_prerelease') === 'on'
        };

        // Basic validation
        if (!data.product_id) {
            this.showError('Please select a product');
            return;
        }

        if (!data.name) {
            this.showError('Release name is required');
            return;
        }

        this.setLoading(true);

        try {
            const response = await fetch('/api/v1/releases', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCSRFToken()
                },
                body: JSON.stringify(data)
            });

            if (response.ok) {
                const result: CreateReleaseResponse = await response.json();
                NotificationManager.showSuccess(`Release "${result.name}" created successfully!`);

                // Close modal and reload page to show new release
                if (this.modal) {
                    this.modal.hide();
                }
                window.location.reload();
            } else {
                // Handle error response
                let errorMessage = 'Failed to create release';

                try {
                    const errorData = await response.json();
                    if (errorData.detail) {
                        errorMessage = errorData.detail;
                    } else if (errorData.message) {
                        errorMessage = errorData.message;
                    } else if (typeof errorData === 'string') {
                        errorMessage = errorData;
                    }
                } catch {
                    // Response is not JSON (likely HTML error page)
                    errorMessage = `Server error (${response.status}): ${response.statusText}`;
                }

                // Show error in both the modal and as a notification
                this.showError(errorMessage);
                NotificationManager.showError(errorMessage);
            }
        } catch (error) {
            console.error('Error creating release:', error);
            const errorMessage = 'Network error. Please check your connection and try again.';
            this.showError(errorMessage);
            NotificationManager.showError(errorMessage);
        } finally {
            this.setLoading(false);
        }
    }

    private setLoading(loading: boolean): void {
        if (this.createBtn) {
            this.createBtn.disabled = loading;
        }

        if (this.spinner) {
            this.spinner.style.display = loading ? 'inline-block' : 'none';
        }
    }

    private showError(message: string): void {
        if (this.errorDiv) {
            this.errorDiv.textContent = message;
            this.errorDiv.style.display = 'block';
        }
    }

    private hideError(): void {
        if (this.errorDiv) {
            this.errorDiv.style.display = 'none';
        }
    }

    private clearForm(): void {
        if (this.form) {
            this.form.reset();
        }
    }

    private getCSRFToken(): string {
        const csrfInput = document.querySelector('[name=csrfmiddlewaretoken]') as HTMLInputElement;
        return csrfInput?.value || '';
    }

    private initializeEditButtons(): void {
        const editButtons = document.querySelectorAll('.edit-release-btn');
        editButtons.forEach(button => {
            button.addEventListener('click', (event) => {
                const target = event.currentTarget as HTMLElement;
                this.handleEditRelease(target);
            });
        });
    }

    private initializeDeleteButtons(): void {
        const deleteButtons = document.querySelectorAll('.delete-release-btn');
        deleteButtons.forEach(button => {
            button.addEventListener('click', (event) => {
                const target = event.currentTarget as HTMLElement;
                this.handleDeleteRelease(target);
            });
        });
    }

    private handleEditRelease(button: HTMLElement): void {
        const releaseId = button.dataset.releaseId;
        const releaseName = button.dataset.releaseName || '';
        const releaseDescription = button.dataset.releaseDescription || '';
        const isPrerelease = button.dataset.releasePrerelease === 'true';

        if (!releaseId) {
            console.error('Release ID not found in button dataset');
            return;
        }

        // Use the global release CRUD modal if available
        if (window.releaseCrudModal) {
            window.releaseCrudModal.openEdit({
                releaseId,
                releaseName,
                releaseDescription,
                isPrerelease
            });
        } else {
            NotificationManager.showError('Edit functionality not available');
        }
    }

    private async handleDeleteRelease(button: HTMLElement): Promise<void> {
        const releaseId = button.dataset.releaseId;
        const releaseName = button.dataset.releaseName || 'this release';

        if (!releaseId) {
            console.error('Release ID not found in button dataset');
            return;
        }

        // Use the standard confirmation modal pattern
        const confirmed = await NotificationManager.showConfirmation(
            `Are you sure you want to delete "${releaseName}"? This action cannot be undone and will permanently remove the release and all associated data.`,
            'Delete Release',
            'Yes, delete it!',
            'Cancel'
        );

        if (!confirmed) {
            return;
        }

        try {
            const response = await fetch(`/api/v1/releases/${releaseId}`, {
                method: 'DELETE',
                headers: {
                    'X-CSRFToken': this.getCSRFToken(),
                    'Content-Type': 'application/json'
                }
            });

            if (response.ok) {
                NotificationManager.showSuccess(`Release "${releaseName}" deleted successfully!`);
                // Reload the page to refresh the releases list
                window.location.reload();
            } else {
                const errorData = await response.json();
                throw new Error(errorData.detail || 'Failed to delete release');
            }
        } catch (error) {
            console.error('Error deleting release:', error);
            NotificationManager.showError(`Error deleting release: ${error instanceof Error ? error.message : 'Unknown error'}`);
        }
    }
}

// Initialize when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    // Only initialize if we're on a page with the all releases table
    const allReleasesTable = document.querySelector('[data-component="all-releases-table"]');
    if (allReleasesTable) {
        new AllReleasesTable();
    }
});

export default AllReleasesTable;