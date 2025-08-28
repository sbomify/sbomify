/**
 * TypeScript functionality for release create/edit modal
 * Handles both create and edit operations with proper form validation
 */

import { NotificationManager, ApiClient, DomUtils } from '../utils/django-components';

interface ReleaseFormData {
  name: string;
  description?: string;
  is_prerelease: boolean;
  product_id?: string;
}

interface ReleaseCreateData extends ReleaseFormData {
  product_id: string;
}

interface ReleaseEditConfig {
  releaseId: string;
  releaseName: string;
  releaseDescription: string;
  isPrerelease: boolean;
}

export class ReleaseCrudModal {
  private modalId: string;
  private editingReleaseId: string | null = null;
  private defaultProductId: string | null = null;

  // Modal elements
  private modal: HTMLElement | null = null;
  private form: HTMLFormElement | null = null;
  private modalTitle: HTMLElement | null = null;
  private modalIcon: HTMLElement | null = null;
  private submitBtn: HTMLButtonElement | null = null;
  private submitText: HTMLElement | null = null;
  private submitIcon: HTMLElement | null = null;
  private spinner: HTMLElement | null = null;
  private errorDiv: HTMLElement | null = null;

  // Form fields
  private nameField: HTMLInputElement | null = null;
  private descriptionField: HTMLTextAreaElement | null = null;
  private prereleaseField: HTMLInputElement | null = null;


  constructor(modalId: string, defaultProductId?: string) {
    this.modalId = modalId;
    this.defaultProductId = defaultProductId || null;
    this.initialize();
  }

  private initialize(): void {
    this.initializeElements();
    this.attachEventListeners();
  }

  private initializeElements(): void {
    this.modal = DomUtils.getElement(this.modalId);
    this.form = DomUtils.getElement<HTMLFormElement>(`${this.modalId}Form`);
    this.modalTitle = DomUtils.getElement(`${this.modalId}Title`);
    this.modalIcon = DomUtils.getElement(`${this.modalId}Icon`);
    this.submitBtn = DomUtils.getElement<HTMLButtonElement>(`${this.modalId}Submit`);
    this.submitText = DomUtils.getElement(`${this.modalId}SubmitText`);
    this.submitIcon = DomUtils.getElement(`${this.modalId}SubmitIcon`);
    this.spinner = DomUtils.getElement(`${this.modalId}Spinner`);
    this.errorDiv = DomUtils.getElement(`${this.modalId}Error`);

    // Form fields
    this.nameField = DomUtils.getElement<HTMLInputElement>(`${this.modalId}Name`);
    this.descriptionField = DomUtils.getElement<HTMLTextAreaElement>(`${this.modalId}Description`);
    this.prereleaseField = DomUtils.getElement<HTMLInputElement>(`${this.modalId}PreRelease`);
    // Product field not stored as it's only used for form submission

    console.log('Release modal elements found:', {
      modal: !!this.modal,
      form: !!this.form,
      submitBtn: !!this.submitBtn,
      nameField: !!this.nameField
    });
  }

  private attachEventListeners(): void {
    if (!this.modal || !this.form || !this.submitBtn) return;

    // Form submission
    this.form.addEventListener('submit', (e) => {
      e.preventDefault();
      this.handleSave();
    });

    // Submit button click
    this.submitBtn.addEventListener('click', (e) => {
      e.preventDefault();
      this.handleSave();
    });

    // Modal reset on hide
    this.modal.addEventListener('hidden.bs.modal', () => {
      this.resetForm();
    });

    // Focus on name field when modal is shown
    this.modal.addEventListener('shown.bs.modal', () => {
      if (this.nameField) {
        this.nameField.focus();
      }
    });

    // Enter key handling for faster workflow
    this.nameField?.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && e.ctrlKey) {
        e.preventDefault();
        this.handleSave();
      }
    });
  }

  /**
   * Open modal for creating a new release
   */
  public openCreate(): void {
    this.editingReleaseId = null;
    this.setModalMode('create');
    this.resetForm();
    this.showModal();
  }

  /**
   * Open modal for editing an existing release
   */
  public openEdit(config: ReleaseEditConfig): void {
    this.editingReleaseId = config.releaseId;
    this.setModalMode('edit');
    this.populateForm({
      name: config.releaseName,
      description: config.releaseDescription,
      is_prerelease: config.isPrerelease
    });
    this.showModal();
  }

  private setModalMode(mode: 'create' | 'edit'): void {
    const isCreate = mode === 'create';

    if (this.modalTitle) {
      this.modalTitle.textContent = isCreate ? 'Create Release' : 'Edit Release';
    }

    if (this.modalIcon) {
      this.modalIcon.className = isCreate ? 'fas fa-plus text-primary me-2' : 'fas fa-edit text-primary me-2';
    }

    if (this.submitText) {
      this.submitText.textContent = isCreate ? 'Create Release' : 'Update Release';
    }

    if (this.submitIcon) {
      this.submitIcon.className = isCreate ? 'fas fa-plus me-2' : 'fas fa-save me-2';
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
          product_id: formData.product_id || this.defaultProductId || ''
        };

        if (!createData.product_id) {
          this.showError('Product selection is required');
          return;
        }

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

    // Get product_id from either select field or hidden field or default
    let productId = formData.get('product_id') as string;
    if (!productId && this.defaultProductId) {
      productId = this.defaultProductId;
    }

    return {
      name: (formData.get('name') as string)?.trim() || '',
      description: (formData.get('description') as string)?.trim() || undefined,
      is_prerelease: formData.get('is_prerelease') === 'on',
      product_id: productId || undefined
    };
  }

  private validateForm(data: ReleaseFormData): string | null {
    if (!data.name) return 'Release name is required';
    if (data.name.length > 100) return 'Release name is too long (max 100 characters)';
    if (!this.editingReleaseId && !data.product_id) return 'Product selection is required';
    return null;
  }

  private populateForm(data: Partial<ReleaseFormData>): void {
    if (this.nameField && data.name !== undefined) {
      this.nameField.value = data.name;
    }

    if (this.descriptionField && data.description !== undefined) {
      this.descriptionField.value = data.description || '';
    }

    if (this.prereleaseField && data.is_prerelease !== undefined) {
      this.prereleaseField.checked = data.is_prerelease;
    }
  }

  private resetForm(): void {
    if (this.form) {
      this.form.reset();
    }

    this.hideError();
    this.editingReleaseId = null;
    this.setModalMode('create');

    // Clear validation states
    this.form?.querySelectorAll('.is-invalid').forEach(el => el.classList.remove('is-invalid'));
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
    if (this.submitBtn) this.submitBtn.disabled = loading;
    if (this.spinner) this.spinner.style.display = loading ? 'inline-block' : 'none';
    if (this.modal) {
      if (loading) {
        this.modal.classList.add('loading');
      } else {
        this.modal.classList.remove('loading');
      }
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
}

// Auto-initialization for standard modal IDs
document.addEventListener('DOMContentLoaded', () => {
  // Initialize for create release modal (standard pattern)
  const createModal = document.getElementById('createReleaseModal');
  if (createModal) {
    const productId = createModal.dataset.productId;
    window.releaseCrudModal = new ReleaseCrudModal('createReleaseModal', productId);
  }

  // Initialize for other release modals if they exist
  const releaseModal = document.getElementById('releaseModal');
  if (releaseModal) {
    const productId = releaseModal.dataset.productId;
    window.releaseCrudModal = new ReleaseCrudModal('releaseModal', productId);
  }
});

// ReleaseCrudModal exported above
