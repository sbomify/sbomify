/**
 * TypeScript functionality for releases CRUD operations
 * Handles create, update, delete operations only - data is server-side rendered
 */

import { NotificationManager, ApiClient, DomUtils } from '../utils/django-components';

interface ReleaseFormData {
  name: string;
  description?: string;
  is_prerelease: boolean;
}

interface ReleaseCreateData extends ReleaseFormData {
  product_id: string;
}

class ReleasesCrudManager {
  private productId: string;
  private hasCrudPermissions: boolean;
  private editingReleaseId: string | null = null;

  // Modal elements
  private modal: HTMLElement | null = null;
  private form: HTMLFormElement | null = null;
  private modalTitle: HTMLElement | null = null;
  private saveBtn: HTMLButtonElement | null = null;
  private saveText: HTMLElement | null = null;
  private spinner: HTMLElement | null = null;
  private errorDiv: HTMLElement | null = null;

  constructor(productId: string, hasCrudPermissions: boolean) {
    this.productId = productId;
    this.hasCrudPermissions = hasCrudPermissions;
    this.initialize();
  }

  private initialize(): void {
    this.initializeElements();
    this.attachEventListeners();
  }

  private initializeElements(): void {
    // Only initialize modal elements if we have CRUD permissions
    if (this.hasCrudPermissions) {
      this.modal = DomUtils.getElement('createReleaseModal');
      this.form = DomUtils.getElement<HTMLFormElement>('createReleaseForm');
      this.modalTitle = DomUtils.getElement('releaseModalTitle');
      this.saveBtn = DomUtils.getElement<HTMLButtonElement>('createReleaseBtn');
      this.saveText = DomUtils.getElement('createReleaseText');
      this.spinner = DomUtils.getElement('createReleaseSpinner');
      this.errorDiv = DomUtils.getElement('createReleaseError');

      console.log('Release modal elements found:', {
        modal: !!this.modal,
        form: !!this.form,
        btn: !!this.saveBtn,
        title: !!this.modalTitle
      });
    }
  }

  private attachEventListeners(): void {
    // Edit button listeners
    this.attachEditButtonListeners();

    // Delete button listeners
    this.attachDeleteButtonListeners();

    // Modal listeners (only if elements exist)
    if (this.modal && this.form && this.saveBtn) {
      // Save button
      this.saveBtn.addEventListener('click', (e) => {
        e.preventDefault();
        this.handleSave();
      });

      // Form submission
      this.form.addEventListener('submit', (e) => {
        e.preventDefault();
        this.handleSave();
      });

      // Modal reset
      this.modal.addEventListener('hidden.bs.modal', () => {
        this.resetForm();
      });
    }
  }

  private attachEditButtonListeners(): void {
    const editButtons = DomUtils.getElements<HTMLButtonElement>('.edit-release-btn');
    console.log('Found edit release buttons:', editButtons.length);

    editButtons.forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        this.handleEdit(btn);
      });
    });
  }

  private attachDeleteButtonListeners(): void {
    const deleteButtons = DomUtils.getElements<HTMLButtonElement>('.delete-release-btn');

    deleteButtons.forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        this.handleDelete(btn);
      });
    });
  }

  private handleEdit(button: HTMLButtonElement): void {
    const releaseId = button.dataset.releaseId;
    const releaseName = button.dataset.releaseName || '';
    const releaseDescription = button.dataset.releaseDescription || '';
    const isPrerelease = button.dataset.releasePrerelease === 'true';

    if (!releaseId) {
      console.error('Release ID not found in button dataset');
      return;
    }

    console.log('Edit data:', { releaseId, releaseName, releaseDescription, isPrerelease });

    // Check if modal exists
    if (!this.modal) {
      console.error('Cannot edit: Modal not available');
      NotificationManager.showError('Edit functionality not available');
      return;
    }

    this.editingReleaseId = releaseId;

    // Update modal
    if (this.modalTitle) this.modalTitle.textContent = 'Edit Release';
    if (this.saveText) this.saveText.textContent = 'Update Release';

    // Populate form
    this.populateForm({
      name: releaseName,
      description: releaseDescription,
      is_prerelease: isPrerelease
    });

    // Show modal
    this.showModal();
  }

  private async handleDelete(button: HTMLButtonElement): Promise<void> {
    const releaseId = button.dataset.releaseId;
    const releaseName = button.dataset.releaseName || 'this release';

    if (!releaseId) return;

    const confirmed = await NotificationManager.showConfirmation(
      `Are you sure you want to delete the release "${releaseName}"? This action cannot be undone.`
    );

    if (!confirmed) return;

    try {
      await ApiClient.delete(`/api/v1/releases/${releaseId}`);
      NotificationManager.showSuccess('Release deleted successfully!');

      // Reload page to show updated data
      window.location.reload();
    } catch (error) {
      console.error('Error deleting release:', error);
      NotificationManager.showError(`Error deleting release: ${error instanceof Error ? error.message : 'Unknown error'}`);
    }
  }

  private async handleSave(): Promise<void> {
    if (!this.form) return;

    const formData = this.getFormData();
    const validation = this.validateForm(formData);

    if (validation) {
      this.showError(validation);
      return;
    }

    try {
      this.setLoading(true);
      this.hideError();

      if (this.editingReleaseId) {
        // Update existing release
        await ApiClient.patch(`/api/v1/releases/${this.editingReleaseId}`, formData);
        NotificationManager.showSuccess('Release updated successfully!');
      } else {
        // Create new release
        const createData: ReleaseCreateData = {
          ...formData,
          product_id: this.productId
        };
        await ApiClient.post('/api/v1/releases', createData);
        NotificationManager.showSuccess('Release created successfully!');
      }

      this.hideModal();

      // Reload page to show updated data
      window.location.reload();

    } catch (error) {
      console.error('Error saving release:', error);
      this.showError(`Error saving release: ${error instanceof Error ? error.message : 'Unknown error'}`);
    } finally {
      this.setLoading(false);
    }
  }

  private getFormData(): ReleaseFormData {
    if (!this.form) throw new Error('Form not found');

    const formData = new FormData(this.form);
    return {
      name: formData.get('name') as string,
      description: formData.get('description') as string || undefined,
      is_prerelease: formData.get('is_prerelease') === 'on'
    };
  }

  private validateForm(data: ReleaseFormData): string | null {
    if (!data.name?.trim()) return 'Release name is required';
    return null;
  }

  private populateForm(data: ReleaseFormData): void {
    if (!this.form) return;

    const nameField = this.form.querySelector('#releaseName') as HTMLInputElement;
    const descField = this.form.querySelector('#releaseDescription') as HTMLTextAreaElement;
    const prereleaseField = this.form.querySelector('#isPrerelease') as HTMLInputElement;

    if (nameField) nameField.value = data.name;
    if (descField) descField.value = data.description || '';
    if (prereleaseField) prereleaseField.checked = data.is_prerelease;
  }

  private resetForm(): void {
    if (this.form) this.form.reset();
    this.hideError();
    this.editingReleaseId = null;
    if (this.modalTitle) this.modalTitle.textContent = 'Create Release';
    if (this.saveText) this.saveText.textContent = 'Create Release';
  }

  private showModal(): void {
    if (!this.modal) return;
    const bootstrapModal = new window.bootstrap.Modal(this.modal);
    bootstrapModal.show();
  }

  private hideModal(): void {
    if (!this.modal) return;
    const bootstrapModal = window.bootstrap.Modal.getInstance(this.modal);
    if (bootstrapModal) bootstrapModal.hide();
  }

  private setLoading(loading: boolean): void {
    if (this.saveBtn) this.saveBtn.disabled = loading;
    if (this.spinner) this.spinner.style.display = loading ? 'inline-block' : 'none';
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
}

// Initialize when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
  const releasesContainer = document.querySelector('[data-releases-table]') as HTMLElement;

  if (releasesContainer) {
    const productId = releasesContainer.dataset.productId;
    const hasCrudPermissions = releasesContainer.dataset.hasCrudPermissions === 'true';

    if (productId) {
      console.log('Initializing ReleasesCrudManager for server-side rendered data');
      new ReleasesCrudManager(productId, hasCrudPermissions);
    }
  }
});

export { ReleasesCrudManager };
