/**
 * TypeScript functionality for Django editable field component
 * Handles inline editing of fields with modal interface
 */

import { NotificationManager, ApiClient, DomUtils } from '../utils/django-components';

// Bootstrap type - using the same interface defined in django-components
interface BootstrapModal {
  show(): void;
  hide(): void;
}

interface EditableFieldData {
  itemType: string;
  itemId: string;
  fieldName: string;
  fieldType: string;
  currentValue: string;
  placeholder: string;
}

export class EditableFieldManager {
  private currentEditingField: HTMLElement | null = null;
  private modal: HTMLElement | null = null;
  private form: HTMLFormElement | null = null;
  private input: HTMLInputElement | null = null;
  private saveBtn: HTMLButtonElement | null = null;
  private bootstrapModal: BootstrapModal | null = null;

  constructor() {
    this.initialize();
  }

  private initialize(): void {
    this.initializeElements();
    this.attachEventListeners();
  }

  private initializeElements(): void {
    this.modal = DomUtils.getElement('editFieldModal');
    this.form = DomUtils.getElement<HTMLFormElement>('editFieldForm');
    this.input = DomUtils.getElement<HTMLInputElement>('fieldValue');
    this.saveBtn = DomUtils.getElement<HTMLButtonElement>('saveFieldBtn');

    if (!this.modal || !this.form || !this.input || !this.saveBtn) {
      console.warn('EditableFieldManager: Required elements not found');
      return;
    }

    // Initialize Bootstrap modal
    this.bootstrapModal = new window.bootstrap.Modal(this.modal);
  }

  private attachEventListeners(): void {
    if (!this.modal || !this.form || !this.saveBtn) return;

    // Attach click listeners to all editable fields
    this.attachFieldListeners();

    // Save button handler
    this.saveBtn.addEventListener('click', (e) => {
      e.preventDefault();
      this.handleSave();
    });

    // Form submission handler
    this.form.addEventListener('submit', (e) => {
      e.preventDefault();
      this.handleSave();
    });

    // Modal hidden handler
    this.modal.addEventListener('hidden.bs.modal', () => {
      this.cleanupEditingState();
    });
  }

  private attachFieldListeners(): void {
    const editableFields = DomUtils.getElements<HTMLElement>('.editable-field');

    editableFields.forEach(element => {
      element.addEventListener('click', (e) => {
        e.preventDefault();
        this.handleFieldClick(element);
      });
    });
  }

    private handleFieldClick(element: HTMLElement): void {
    if (!this.modal || !this.input || !this.bootstrapModal) return;

    this.currentEditingField = element;

    const data = this.extractFieldData(element);
    if (!data) return;

    // Update modal title
    const modalTitle = this.modal.querySelector('.modal-title');
    if (modalTitle) {
      modalTitle.textContent = `Edit ${data.fieldName.charAt(0).toUpperCase() + data.fieldName.slice(1)}`;
    }

    // Update field label to be more specific
    const fieldLabel = this.modal.querySelector('#fieldLabel');
    if (fieldLabel) {
      const labelMap: Record<string, string> = {
        'name': 'Name',
        'title': 'Title',
        'description': 'Description',
        'version': 'Version',
        'value': 'Value'
      };
      fieldLabel.textContent = labelMap[data.fieldName] || data.fieldName.charAt(0).toUpperCase() + data.fieldName.slice(1);
    }

    // Update input type and value
    this.input.type = data.fieldType;
    this.input.value = data.currentValue;

    // Mark as editing
    element.classList.add('editing');

    // Show modal and focus input
    this.bootstrapModal.show();

    // Focus input after modal is shown
    this.modal.addEventListener('shown.bs.modal', () => {
      if (this.input) this.input.focus();
    }, { once: true });
  }

  private extractFieldData(element: HTMLElement): EditableFieldData | null {
    const dataset = element.dataset;

    if (!dataset.itemType || !dataset.itemId || !dataset.fieldName) {
      console.error('EditableFieldManager: Missing required data attributes');
      return null;
    }

    return {
      itemType: dataset.itemType,
      itemId: dataset.itemId,
      fieldName: dataset.fieldName,
      fieldType: dataset.fieldType || 'text',
      currentValue: dataset.currentValue || '',
      placeholder: dataset.placeholder || 'Click to edit...'
    };
  }

  private async handleSave(): Promise<void> {
    if (!this.currentEditingField || !this.input) return;

    const data = this.extractFieldData(this.currentEditingField);
    if (!data) return;

    const newValue = this.input.value.trim();

    if (!newValue) {
      NotificationManager.showError('Value cannot be empty');
      return;
    }

    try {
      // Disable save button during request
      if (this.saveBtn) this.saveBtn.disabled = true;

      await ApiClient.patch(`/api/v1/${data.itemType}s/${data.itemId}`, {
        [data.fieldName]: newValue
      });

      // Update the display
      this.updateFieldDisplay(newValue);

      // Update data attribute
      this.currentEditingField.dataset.currentValue = newValue;

      // Show success feedback
      this.showSuccessFeedback();

      // Hide modal
      if (this.bootstrapModal) {
        this.bootstrapModal.hide();
      }

      NotificationManager.showSuccess('Field updated successfully');

    } catch (error) {
      console.error('Error updating field:', error);
      NotificationManager.showError(`Error updating field: ${error instanceof Error ? error.message : 'Unknown error'}`);
    } finally {
      // Re-enable save button
      if (this.saveBtn) this.saveBtn.disabled = false;
    }
  }

  private updateFieldDisplay(newValue: string): void {
    if (!this.currentEditingField) return;

    const placeholderSpan = this.currentEditingField.querySelector('.placeholder-text');

    if (placeholderSpan) {
      // Replace placeholder with actual value
      this.currentEditingField.innerHTML = `${newValue}<i class="fas fa-edit edit-icon ms-2"></i>`;
    } else {
      // Update existing text node
      const textNode = this.currentEditingField.firstChild;
      if (textNode && textNode.nodeType === Node.TEXT_NODE) {
        textNode.textContent = newValue;
      }
    }
  }

  private showSuccessFeedback(): void {
    if (!this.currentEditingField) return;

    // Temporary success styling
    const originalBackground = this.currentEditingField.style.backgroundColor;
    this.currentEditingField.style.backgroundColor = '#dcfce7';

    setTimeout(() => {
      if (this.currentEditingField) {
        this.currentEditingField.style.backgroundColor = originalBackground;
      }
    }, 2000);
  }

  private cleanupEditingState(): void {
    if (this.currentEditingField) {
      this.currentEditingField.classList.remove('editing');
      this.currentEditingField = null;
    }
  }

  // Public method to refresh field listeners (useful after dynamic content updates)
  public refreshFieldListeners(): void {
    this.attachFieldListeners();
  }
}

// Initialize when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
  // Check if editable fields exist on the page
  const editableFields = document.querySelectorAll('.editable-field');

  if (editableFields.length > 0) {
    console.log('Initializing EditableFieldManager for', editableFields.length, 'fields');
    new EditableFieldManager();
  }
});

// Export for potential external usage
export default EditableFieldManager;
