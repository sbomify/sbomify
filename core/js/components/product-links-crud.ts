/**
 * TypeScript functionality for product links CRUD operations
 * Handles create, update, delete operations only - data is server-side rendered
 */

import { NotificationManager, ApiClient, DomUtils } from '../utils/django-components';

interface ProductLinkFormData {
  link_type: string;
  title: string;
  url: string;
  description?: string;
}

class ProductLinksCrudManager {
  private productId: string;
  private hasCrudPermissions: boolean;
  private editingLinkId: string | null = null;

  // Modal elements
  private modal: HTMLElement | null = null;
  private form: HTMLFormElement | null = null;
  private modalTitle: HTMLElement | null = null;
  private saveBtn: HTMLButtonElement | null = null;
  private errorDiv: HTMLElement | null = null;

  constructor(productId: string, hasCrudPermissions: boolean) {
    this.productId = productId;
    this.hasCrudPermissions = hasCrudPermissions;
    this.initialize();
  }

  private initialize(): void {
    if (!this.hasCrudPermissions) return;

    this.initializeElements();
    this.attachEventListeners();
  }

  private initializeElements(): void {
    this.modal = DomUtils.getElement('addLinkModal');
    this.form = DomUtils.getElement<HTMLFormElement>('linkForm');
    this.modalTitle = DomUtils.getElement('linkModalTitle');
    this.saveBtn = DomUtils.getElement<HTMLButtonElement>('saveLinkBtn');
    this.errorDiv = DomUtils.getElement('linkFormError');
  }

  private attachEventListeners(): void {
    if (!this.modal || !this.form || !this.saveBtn) return;

    // Edit button listeners
    this.attachEditButtonListeners();

    // Delete button listeners
    this.attachDeleteButtonListeners();

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

  private attachEditButtonListeners(): void {
    const editButtons = DomUtils.getElements<HTMLButtonElement>('.edit-link-btn');

    editButtons.forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        this.handleEdit(btn);
      });
    });
  }

  private attachDeleteButtonListeners(): void {
    const deleteButtons = DomUtils.getElements<HTMLButtonElement>('.delete-link-btn');

    deleteButtons.forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        this.handleDelete(btn);
      });
    });
  }

  private handleEdit(button: HTMLButtonElement): void {
    const linkId = button.dataset.linkId;
    const linkType = button.dataset.linkType || '';
    const linkTitle = button.dataset.linkTitle || '';
    const linkUrl = button.dataset.linkUrl || '';
    const linkDescription = button.dataset.linkDescription || '';

    if (!linkId) return;

        this.editingLinkId = linkId;

    // Update modal title and button text
    if (this.modalTitle) this.modalTitle.textContent = 'Edit Link';

    const saveText = document.getElementById('saveLinkText');
    if (saveText) saveText.textContent = 'Update Link';

    // Populate form
    this.populateForm({
      link_type: linkType,
      title: linkTitle,
      url: linkUrl,
      description: linkDescription
    });

    // Show modal
    this.showModal();
  }

  private async handleDelete(button: HTMLButtonElement): Promise<void> {
    const linkId = button.dataset.linkId;
    const linkTitle = button.dataset.linkTitle || 'this link';

    if (!linkId) return;

    const confirmed = await NotificationManager.showConfirmation(
      `Are you sure you want to delete the link "${linkTitle}"? This action cannot be undone.`
    );

    if (!confirmed) return;

    try {
      await ApiClient.delete(`/api/v1/products/${this.productId}/links/${linkId}`);
      NotificationManager.showSuccess('Link deleted successfully!');

      // Reload page to show updated data
      window.location.reload();
    } catch (error) {
      console.error('Error deleting link:', error);
      NotificationManager.showError(`Error deleting link: ${error instanceof Error ? error.message : 'Unknown error'}`);
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

      if (this.editingLinkId) {
        // Update existing link
        await ApiClient.patch(`/api/v1/products/${this.productId}/links/${this.editingLinkId}`, formData);
        NotificationManager.showSuccess('Link updated successfully!');
      } else {
        // Create new link
        await ApiClient.post(`/api/v1/products/${this.productId}/links`, formData);
        NotificationManager.showSuccess('Link created successfully!');
      }

      this.hideModal();

      // Reload page to show updated data
      window.location.reload();

    } catch (error) {
      console.error('Error saving link:', error);
      this.showError(`Error saving link: ${error instanceof Error ? error.message : 'Unknown error'}`);
    } finally {
      this.setLoading(false);
    }
  }

  private getFormData(): ProductLinkFormData {
    if (!this.form) throw new Error('Form not found');

    const formData = new FormData(this.form);
    return {
      link_type: formData.get('link_type') as string,
      title: formData.get('title') as string,
      url: formData.get('url') as string,
      description: formData.get('description') as string || undefined
    };
  }

  private validateForm(data: ProductLinkFormData): string | null {
    if (!data.link_type) return 'Link type is required';
    if (!data.title?.trim()) return 'Title is required';
    if (!data.url?.trim()) return 'URL is required';

    // Basic URL validation
    try {
      new URL(data.url);
    } catch {
      return 'Please enter a valid URL';
    }

    return null;
  }

  private populateForm(data: ProductLinkFormData): void {
    if (!this.form) return;

    const typeField = this.form.querySelector('#linkType') as HTMLSelectElement;
    const titleField = this.form.querySelector('#linkTitle') as HTMLInputElement;
    const urlField = this.form.querySelector('#linkUrl') as HTMLInputElement;
    const descField = this.form.querySelector('#linkDescription') as HTMLTextAreaElement;

    if (typeField) typeField.value = data.link_type;
    if (titleField) titleField.value = data.title;
    if (urlField) urlField.value = data.url;
    if (descField) descField.value = data.description || '';
  }

  private resetForm(): void {
    if (this.form) this.form.reset();
    this.hideError();
    this.editingLinkId = null;
    if (this.modalTitle) this.modalTitle.textContent = 'Add Link';

    const saveText = document.getElementById('saveLinkText');
    if (saveText) saveText.textContent = 'Add Link';
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
  const linksContainer = document.querySelector('[data-product-links]') as HTMLElement;

  if (linksContainer) {
    const productId = linksContainer.dataset.productId;
    const hasCrudPermissions = linksContainer.dataset.hasCrudPermissions === 'true';

    if (productId) {
      console.log('Initializing ProductLinksCrudManager for server-side rendered data');
      new ProductLinksCrudManager(productId, hasCrudPermissions);
    }
  }
});

export { ProductLinksCrudManager };
