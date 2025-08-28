/**
 * TypeScript functionality for product identifiers CRUD operations
 * Handles create, update, delete operations only - data is server-side rendered
 */

import { NotificationManager, ApiClient, DomUtils } from '../utils/django-components';

// JsBarcode type definitions
interface JsBarcode {
  (element: HTMLElement | SVGElement | string, value: string, options?: unknown): void;
}

interface WindowWithJsBarcode extends Window {
  JsBarcode: JsBarcode;
}

interface ProductIdentifierFormData {
  identifier_type: string;
  value: string;
}

class ProductIdentifiersCrudManager {
  private productId: string;
  private hasCrudPermissions: boolean;
  private teamBillingPlan: string;
  private editingIdentifierId: string | null = null;

  // Modal elements
  private modal: HTMLElement | null = null;
  private form: HTMLFormElement | null = null;
  private modalTitle: HTMLElement | null = null;
  private saveBtn: HTMLButtonElement | null = null;
  private errorDiv: HTMLElement | null = null;

  constructor(productId: string, hasCrudPermissions: boolean, teamBillingPlan: string) {
    this.productId = productId;
    this.hasCrudPermissions = hasCrudPermissions;
    this.teamBillingPlan = teamBillingPlan;
    this.initialize();
  }

  private initialize(): void {
    // Always initialize barcodes, regardless of permissions
    this.generateBarcodes();

    if (!this.hasCrudPermissions || this.teamBillingPlan === 'community') return;

    this.initializeElements();
    this.attachEventListeners();
  }

  private initializeElements(): void {
    this.modal = DomUtils.getElement('addIdentifierModal');
    this.form = DomUtils.getElement<HTMLFormElement>('identifierForm');
    this.modalTitle = DomUtils.getElement('identifierModalTitle');
    this.saveBtn = DomUtils.getElement<HTMLButtonElement>('saveIdentifierBtn');
    this.errorDiv = DomUtils.getElement('identifierFormError');
  }

  private attachEventListeners(): void {
    if (!this.modal || !this.form || !this.saveBtn) return;

    // Edit button listeners
    this.attachEditButtonListeners();

    // Delete button listeners
    this.attachDeleteButtonListeners();

    // Barcode generation listeners
    this.attachBarcodeButtonListeners();

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
    const editButtons = DomUtils.getElements<HTMLButtonElement>('.edit-identifier-btn');

    editButtons.forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        this.handleEdit(btn);
      });
    });
  }

  private attachDeleteButtonListeners(): void {
    const deleteButtons = DomUtils.getElements<HTMLButtonElement>('.delete-identifier-btn');

    deleteButtons.forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        this.handleDelete(btn);
      });
    });
  }

        private async generateBarcodes(): Promise<void> {
    const barcodeContainers = DomUtils.getElements<HTMLElement>('.barcode-container');
    console.log('Found barcode containers:', barcodeContainers.length);

    if (barcodeContainers.length === 0) {
      console.log('No barcode containers found, checking DOM structure...');
      const allContainers = document.querySelectorAll('[data-identifier-value]');
      console.log('Found containers with identifier data:', allContainers.length);
    }

        for (const container of barcodeContainers) {
      const value = container.dataset.identifierValue;
      const type = container.dataset.identifierType;
      const svg = container.querySelector('.barcode-svg') as SVGElement;

      console.log('Processing barcode:', { value, type, hasSvg: !!svg });

      if (value && type && svg) {
        await this.renderBarcode(svg, value, type);
      }
    }
  }

  private attachBarcodeButtonListeners(): void {
    // No longer needed - barcodes are generated on load
    // Keeping method for backward compatibility
  }

  private handleEdit(button: HTMLButtonElement): void {
    const identifierId = button.dataset.identifierId;
    const identifierType = button.dataset.identifierType || '';
    const identifierValue = button.dataset.identifierValue || '';

    if (!identifierId) return;

        this.editingIdentifierId = identifierId;

    // Update modal title and button text
    if (this.modalTitle) this.modalTitle.textContent = 'Edit Identifier';

    const saveText = document.getElementById('saveIdentifierText');
    if (saveText) saveText.textContent = 'Update Identifier';

    // Populate form
    this.populateForm({
      identifier_type: identifierType,
      value: identifierValue
    });

    // Show modal
    this.showModal();
  }

  private async handleDelete(button: HTMLButtonElement): Promise<void> {
    const identifierId = button.dataset.identifierId;
    const identifierValue = button.dataset.identifierValue || 'this identifier';

    if (!identifierId) return;

    const confirmed = await NotificationManager.showConfirmation(
      `Are you sure you want to delete the identifier "${identifierValue}"? This action cannot be undone.`
    );

    if (!confirmed) return;

    try {
      await ApiClient.delete(`/api/v1/products/${this.productId}/identifiers/${identifierId}`);
      NotificationManager.showSuccess('Identifier deleted successfully!');

      // Reload page to show updated data
      window.location.reload();
    } catch (error) {
      console.error('Error deleting identifier:', error);
      NotificationManager.showError(`Error deleting identifier: ${error instanceof Error ? error.message : 'Unknown error'}`);
    }
  }

    private async renderBarcode(svg: SVGElement, value: string, type: string): Promise<void> {
    try {
      // Use CDN import for JsBarcode since it's not in package.json
      const JsBarcode = await this.loadJsBarcode();

      // Generate barcode as SVG with integrated text
      JsBarcode(svg, value, {
        format: this.getBarcodeFormat(type),
        width: 1.3,
        height: 40,
        displayValue: true,
        fontSize: 12,
        textMargin: 4,
        textPosition: 'bottom',
        background: '#ffffff',
        lineColor: '#000000',
        margin: 8,
        marginTop: 5,
        marginBottom: 5,
        textAlign: 'center',
        font: 'monospace'
      });

    } catch (error) {
      console.error('Error rendering barcode:', error);
      // Show fallback text
      svg.parentElement!.innerHTML = '<span class="text-muted small">Barcode error</span>';
    }
  }



    private async loadJsBarcode(): Promise<JsBarcode> {
    // Use CDN import for JsBarcode since it might not be in package.json
    if (!(window as WindowWithJsBarcode).JsBarcode) {
      const script = document.createElement('script');
      script.src = 'https://cdn.jsdelivr.net/npm/jsbarcode@3.11.5/dist/JsBarcode.all.min.js';
      document.head.appendChild(script);

      return new Promise((resolve, reject) => {
        script.onload = () => resolve((window as WindowWithJsBarcode).JsBarcode);
        script.onerror = reject;
      });
    }
    return (window as WindowWithJsBarcode).JsBarcode;
  }

  private getBarcodeFormat(type: string): string {
    switch (type.toLowerCase()) {
      case 'ean':
      case 'ean_13':
        return 'EAN13';
      case 'upc':
      case 'upc_a':
        return 'UPC';
      case 'isbn':
      case 'isbn_13':
        return 'EAN13';
      case 'gtin':
      case 'gtin_13':
        return 'EAN13';
      default:
        return 'CODE128';
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

      if (this.editingIdentifierId) {
        // Update existing identifier
        await ApiClient.patch(`/api/v1/products/${this.productId}/identifiers/${this.editingIdentifierId}`, formData);
        NotificationManager.showSuccess('Identifier updated successfully!');
      } else {
        // Create new identifier
        await ApiClient.post(`/api/v1/products/${this.productId}/identifiers`, formData);
        NotificationManager.showSuccess('Identifier created successfully!');
      }

      this.hideModal();

      // Reload page to show updated data
      window.location.reload();

    } catch (error) {
      console.error('Error saving identifier:', error);
      this.showError(`Error saving identifier: ${error instanceof Error ? error.message : 'Unknown error'}`);
    } finally {
      this.setLoading(false);
    }
  }

  private getFormData(): ProductIdentifierFormData {
    if (!this.form) throw new Error('Form not found');

    const formData = new FormData(this.form);
    return {
      identifier_type: formData.get('identifier_type') as string,
      value: formData.get('value') as string
    };
  }

  private validateForm(data: ProductIdentifierFormData): string | null {
    if (!data.identifier_type) return 'Identifier type is required';
    if (!data.value?.trim()) return 'Value is required';
    return null;
  }

  private populateForm(data: ProductIdentifierFormData): void {
    if (!this.form) return;

    const typeField = this.form.querySelector('#identifierType') as HTMLSelectElement;
    const valueField = this.form.querySelector('#identifierValue') as HTMLInputElement;

    if (typeField) typeField.value = data.identifier_type;
    if (valueField) valueField.value = data.value;
  }

  private resetForm(): void {
    if (this.form) this.form.reset();
    this.hideError();
    this.editingIdentifierId = null;
    if (this.modalTitle) this.modalTitle.textContent = 'Add Identifier';

    const saveText = document.getElementById('saveIdentifierText');
    if (saveText) saveText.textContent = 'Add Identifier';
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
  const identifiersContainer = document.querySelector('[data-product-identifiers]') as HTMLElement;

  if (identifiersContainer) {
    const productId = identifiersContainer.dataset.productId;
    const hasCrudPermissions = identifiersContainer.dataset.hasCrudPermissions === 'true';
    const teamBillingPlan = identifiersContainer.dataset.teamBillingPlan || 'community';

    if (productId) {
      console.log('Initializing ProductIdentifiersCrudManager for server-side rendered data');
      new ProductIdentifiersCrudManager(productId, hasCrudPermissions, teamBillingPlan);
    }
  }
});

export { ProductIdentifiersCrudManager };
