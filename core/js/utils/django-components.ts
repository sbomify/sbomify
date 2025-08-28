/**
 * Shared TypeScript utilities for Django template components
 * Provides common functionality like API calls, notifications, form handling
 */

// Bootstrap 5 native notifications - no external dependencies

// Bootstrap type definitions
interface BootstrapToast {
  show(): void;
  hide(): void;
}

interface BootstrapModal {
  show(): void;
  hide(): void;
}

interface BootstrapPopover {
  show(): void;
  hide(): void;
}

declare global {
  interface Window {
    bootstrap: {
      Toast: new (element: Element, options?: Record<string, unknown>) => BootstrapToast;
      Modal: new (element: Element, options?: Record<string, unknown>) => BootstrapModal;
      Popover: new (element: Element, options?: Record<string, unknown>) => BootstrapPopover;
    };
  }
}

// Types
export interface ApiResponse<T = unknown> {
  data?: T;
  detail?: string;
  error_code?: string;
}

export interface FormValidationError {
  field: string;
  message: string;
}

// Additional types removed - using built-in types

// Bootstrap 5 Toast Notification utilities
export class NotificationManager {
  private static toastContainer: HTMLElement | null = null;

  private static ensureToastContainer(): HTMLElement {
    if (!this.toastContainer) {
      // Create toast container if it doesn't exist
      this.toastContainer = document.createElement('div');
      this.toastContainer.className = 'toast-container position-fixed top-0 end-0 p-3';
      this.toastContainer.style.zIndex = '1055';
      document.body.appendChild(this.toastContainer);
    }
    return this.toastContainer;
  }

  private static createToast(message: string, type: 'success' | 'error' | 'warning', duration: number = 3000): void {
    const container = this.ensureToastContainer();
    const toastId = 'toast_' + Date.now();

    const iconMap = {
      success: 'fas fa-check-circle text-success',
      error: 'fas fa-exclamation-circle text-danger',
      warning: 'fas fa-exclamation-triangle text-warning'
    };

        const toastHtml = `
      <div class="toast border-0"
           id="${toastId}" role="alert" aria-live="assertive" aria-atomic="true"
           style="min-width: 380px; max-width: 480px; border-radius: 16px;
                  background: ${this.getToastBackground(type)};
                  backdrop-filter: blur(20px);
                  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.12), 0 2px 8px rgba(0, 0, 0, 0.08);">
        <div class="d-flex align-items-center p-4">
          <div class="me-3">
            <div class="rounded-circle d-flex align-items-center justify-content-center"
                 style="width: 36px; height: 36px; background: ${this.getIconBackground(type)};
                        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);">
              <i class="${iconMap[type]}" style="font-size: 1rem; color: white;"></i>
            </div>
          </div>
          <div class="flex-grow-1">
                         <div class="fw-bold mb-1" style="font-size: 0.95rem; color: ${this.getTextColor()};">
               ${this.getToastTitle(type)}
             </div>
             <div style="font-size: 0.875rem; line-height: 1.4; color: ${this.getMessageColor()};">
               ${message}
             </div>
          </div>
          <button type="button" class="btn-close ms-3" data-bs-dismiss="toast" aria-label="Close"
                  style="filter: ${type === 'error' ? 'invert(1)' : 'none'}; opacity: 0.6;"></button>
        </div>
      </div>
    `;

    // Add toast to container
    container.insertAdjacentHTML('beforeend', toastHtml);

    // Initialize and show toast
    const toastElement = document.getElementById(toastId);
    if (toastElement) {
      const bsToast = new window.bootstrap.Toast(toastElement, {
        autohide: true,
        delay: duration
      });

      bsToast.show();

      // Remove from DOM after hiding
      toastElement.addEventListener('hidden.bs.toast', () => {
        toastElement.remove();
      });
    }
  }

  static showSuccess(message: string): Promise<void> {
    this.createToast(message, 'success', 3000);
    return Promise.resolve();
  }

  static showError(message: string): Promise<void> {
    this.createToast(message, 'error', 5000);
    return Promise.resolve();
  }

  static showWarning(message: string): Promise<void> {
    this.createToast(message, 'warning', 4000);
    return Promise.resolve();
  }

    private static getToastBackground(type: 'success' | 'error' | 'warning'): string {
    const backgrounds = {
      success: 'linear-gradient(135deg, rgba(16, 185, 129, 0.95), rgba(5, 150, 105, 0.95))',
      error: 'linear-gradient(135deg, rgba(239, 68, 68, 0.95), rgba(220, 38, 38, 0.95))',
      warning: 'linear-gradient(135deg, rgba(245, 158, 11, 0.95), rgba(217, 119, 6, 0.95))'
    };
    return backgrounds[type];
  }

  private static getIconBackground(type: 'success' | 'error' | 'warning'): string {
    const backgrounds = {
      success: 'rgba(255, 255, 255, 0.2)',
      error: 'rgba(255, 255, 255, 0.2)',
      warning: 'rgba(255, 255, 255, 0.2)'
    };
    return backgrounds[type];
  }

  private static getTextColor(): string {
    return 'rgba(255, 255, 255, 0.95)'; // White text for all types
  }

  private static getMessageColor(): string {
    return 'rgba(255, 255, 255, 0.85)'; // Slightly transparent white
  }

  private static getToastTitle(type: 'success' | 'error' | 'warning'): string {
    const titles = {
      success: 'Success',
      error: 'Error',
      warning: 'Warning'
    };
    return titles[type];
  }

  // Initialize global toast event listener
  static initialize(): void {
    document.addEventListener('show-toast', ((event: Event) => {
      const customEvent = event as CustomEvent<{message: string; type: string}>;
      const { message, type } = customEvent.detail;
      switch (type) {
        case 'success':
          this.showSuccess(message);
          break;
        case 'error':
          this.showError(message);
          break;
        case 'warning':
          this.showWarning(message);
          break;
      }
    }) as EventListener);
  }

  static async showConfirmation(
    message: string,
    title: string = 'Are you sure?',
    confirmText: string = 'Yes, delete it!',
    cancelText: string = 'Cancel'
  ): Promise<boolean> {
    return new Promise((resolve) => {
      // Create Bootstrap 5 modal dynamically
      const modalId = 'confirmModal_' + Date.now();
      const modalHtml = `
        <div class="modal fade" id="${modalId}" tabindex="-1" aria-hidden="true">
          <div class="modal-dialog modal-dialog-centered">
            <div class="modal-content modern-modal">
              <div class="modal-header modern-modal-header border-0">
                <h5 class="modal-title fw-bold">
                  <i class="fas fa-exclamation-triangle text-warning me-2"></i>
                  ${title}
                </h5>
                <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
              </div>
              <div class="modal-body px-4 py-3">
                <div class="alert alert-warning border-0 mb-3">
                  <div class="d-flex align-items-center">
                    <i class="fas fa-exclamation-triangle text-warning me-2 fs-5"></i>
                    <div>
                      <strong>Warning:</strong>
                      This action cannot be undone and will permanently remove the workspace and all associated data from the system.
                    </div>
                  </div>
                </div>
                <p class="mb-0 text-center">${message}</p>
              </div>
              <div class="modal-footer modern-modal-footer border-0 px-4 py-3">
                <button type="button" class="btn btn-outline-secondary modern-btn-secondary" data-bs-dismiss="modal">${cancelText}</button>
                <button type="button" class="btn btn-danger px-4 modern-btn-danger" id="${modalId}_confirm">
                  <i class="fas fa-trash me-2"></i>${confirmText}
                </button>
              </div>
            </div>
          </div>
        </div>
      `;

      // Add modal to DOM
      document.body.insertAdjacentHTML('beforeend', modalHtml);
      const modalElement = document.getElementById(modalId);
      const confirmBtn = document.getElementById(`${modalId}_confirm`);

      if (!modalElement || !confirmBtn) {
        resolve(false);
        return;
      }

      // Initialize Bootstrap modal
      const bootstrapModal = new window.bootstrap.Modal(modalElement);

      // Handle confirm button
      confirmBtn.addEventListener('click', () => {
        bootstrapModal.hide();
        resolve(true);
      });

      // Handle modal hidden (cancel)
      modalElement.addEventListener('hidden.bs.modal', () => {
        document.body.removeChild(modalElement);
        resolve(false);
      }, { once: true });

      // Show modal
      bootstrapModal.show();
    });
  }
}

// API utilities
export class ApiClient {
  private static getCsrfToken(): string {
    const token = (document.querySelector('[name=csrfmiddlewaretoken]') as HTMLInputElement)?.value;
    if (!token) {
      console.warn('CSRF token not found');
    }
    return token || '';
  }

  private static async handleResponse<T>(response: Response): Promise<T> {
    if (!response.ok) {
      const error: ApiResponse = await response.json().catch(() => ({}));
      throw new Error(error.detail || `HTTP ${response.status}`);
    }
    return response.json();
  }

  static async get<T>(url: string): Promise<T> {
    const response = await fetch(url, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
      }
    });
    return this.handleResponse<T>(response);
  }

  static async post<T>(url: string, data: unknown): Promise<T> {
    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': this.getCsrfToken()
      },
      body: JSON.stringify(data)
    });
    return this.handleResponse<T>(response);
  }

  static async patch<T>(url: string, data: unknown): Promise<T> {
    const response = await fetch(url, {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': this.getCsrfToken()
      },
      body: JSON.stringify(data)
    });
    return this.handleResponse<T>(response);
  }

  static async put<T>(url: string, data: unknown): Promise<T> {
    const response = await fetch(url, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': this.getCsrfToken()
      },
      body: JSON.stringify(data)
    });
    return this.handleResponse<T>(response);
  }

  static async delete<T>(url: string): Promise<T> {
    const response = await fetch(url, {
      method: 'DELETE',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': this.getCsrfToken()
      }
    });
    return this.handleResponse<T>(response);
  }
}

// Form utilities
export class FormManager {
    static getFormData(form: HTMLFormElement): Record<string, unknown> {
    const formData = new FormData(form);
    const data: Record<string, unknown> = {};

    formData.forEach((value, key) => {
      if (typeof value === 'string') {
        data[key] = value.trim();
      } else {
        data[key] = value;
      }
    });

    return data;
  }

  static showFormError(errorElement: HTMLElement | null, message: string): void {
    if (errorElement) {
      errorElement.textContent = message;
      errorElement.style.display = 'block';
    }
  }

  static hideFormError(errorElement: HTMLElement | null): void {
    if (errorElement) {
      errorElement.style.display = 'none';
    }
  }

  static setLoadingState(
    button: HTMLButtonElement | null,
    spinner: HTMLElement | null,
    loading: boolean
  ): void {
    if (button) {
      button.disabled = loading;
    }
    if (spinner) {
      spinner.style.display = loading ? 'inline-block' : 'none';
    }
  }
}

// Modal utilities
export class ModalManager {
  static show(modalId: string): void {
    const modal = document.getElementById(modalId);
    if (modal && window.bootstrap) {
      const bootstrapModal = new window.bootstrap.Modal(modal);
      bootstrapModal.show();
    }
  }

  static hide(modalId: string): void {
    const modal = document.getElementById(modalId);
    if (modal && window.bootstrap) {
      const bootstrapModal = (window.bootstrap.Modal as unknown as { getInstance(el: Element): BootstrapModal | null }).getInstance(modal);
      if (bootstrapModal) {
        bootstrapModal.hide();
      }
    }
  }

  static onHidden(modalId: string, callback: () => void): void {
    const modal = document.getElementById(modalId);
    if (modal) {
      modal.addEventListener('hidden.bs.modal', callback);
    }
  }
}

// DOM utilities
export class DomUtils {
  static getElement<T extends HTMLElement>(id: string): T | null {
    return document.getElementById(id) as T | null;
  }

  static getElements<T extends HTMLElement>(selector: string): NodeListOf<T> {
    return document.querySelectorAll<T>(selector);
  }

  static getDataAttribute(element: HTMLElement, attribute: string): string | undefined {
    return element.dataset[attribute];
  }

  static setDataAttribute(element: HTMLElement, attribute: string, value: string): void {
    element.dataset[attribute] = value;
  }
}

// Base class for Django template components
export abstract class DjangoComponent {
  protected config: Record<string, unknown>;

  constructor(config: Record<string, unknown>) {
    this.config = config;
    this.initialize();
  }

  protected abstract initialize(): void;

  protected showSuccess(message: string): Promise<void> {
    return NotificationManager.showSuccess(message);
  }

  protected showError(message: string): Promise<void> {
    return NotificationManager.showError(message);
  }

  protected async showConfirmation(message: string): Promise<boolean> {
    return NotificationManager.showConfirmation(message);
  }

  protected async apiGet<T>(url: string): Promise<T> {
    return ApiClient.get<T>(url);
  }

  protected async apiPost<T>(url: string, data: unknown): Promise<T> {
    return ApiClient.post<T>(url, data);
  }

  protected async apiPatch<T>(url: string, data: unknown): Promise<T> {
    return ApiClient.patch<T>(url, data);
  }

  protected async apiPut<T>(url: string, data: unknown): Promise<T> {
    return ApiClient.put<T>(url, data);
  }

  protected async apiDelete<T>(url: string): Promise<T> {
    return ApiClient.delete<T>(url);
  }
}

// Component registry for auto-initialization
export class ComponentRegistry {
  private static components: Map<string, new (config: Record<string, unknown>) => DjangoComponent> = new Map();

  static register(selector: string, componentClass: new (config: Record<string, unknown>) => DjangoComponent): void {
    this.components.set(selector, componentClass);
  }

  static initializeAll(): void {
    this.components.forEach((ComponentClass, selector) => {
      const elements = document.querySelectorAll(`[data-component="${selector}"]`);
      elements.forEach(element => {
        const config = this.extractConfig(element as HTMLElement);
        new ComponentClass(config);
      });
    });
  }

  private static extractConfig(element: HTMLElement): Record<string, unknown> {
    const config: Record<string, unknown> = {};

    for (const key in element.dataset) {
      if (key !== 'component') {
        config[key] = element.dataset[key];
      }
    }

    return config;
  }
}

// Shared button rendering utilities
export class ButtonRenderer {
  static renderActionButtons(
    itemId: string,
    itemType: string,
    hasCrudPermissions: boolean,
    options: {
      showView?: boolean;
      showDownload?: boolean;
      showEdit?: boolean;
      showDelete?: boolean;
      viewUrl?: string;
      downloadUrl?: string;
      editDisabled?: boolean;
      deleteDisabled?: boolean;
      itemName?: string;
    } = {}
  ): string {
    if (!hasCrudPermissions) return '';

    const {
      showView = false,
      showDownload = false,
      showEdit = true,
      showDelete = true,
      viewUrl = '',
      downloadUrl = '',
      editDisabled = false,
      deleteDisabled = false,
      itemName = ''
    } = options;

    const buttons: string[] = [];

    // View button
    if (showView && viewUrl) {
      buttons.push(`
        <a href="${viewUrl}" class="btn btn-outline-primary btn-sm" title="View">
          <i class="fas fa-eye"></i>
        </a>
      `);
    }

    // Download button
    if (showDownload && downloadUrl) {
      buttons.push(`
        <a href="${downloadUrl}" class="btn btn-outline-success btn-sm" title="Download">
          <i class="fas fa-download"></i>
        </a>
      `);
    }

    // Edit button
    if (showEdit && !editDisabled) {
      buttons.push(`
        <button class="btn btn-outline-primary btn-sm edit-${itemType}-btn"
                title="Edit" data-${itemType}-id="${itemId}">
          <i class="fas fa-edit"></i>
        </button>
      `);
    }

    // Delete button
    if (showDelete && !deleteDisabled) {
      buttons.push(`
        <button class="btn btn-outline-danger btn-sm delete-${itemType}-btn"
                title="Delete" data-${itemType}-id="${itemId}"
                ${itemName ? `data-${itemType}-name="${itemName}"` : ''}>
          <i class="fas fa-trash-alt"></i>
        </button>
      `);
    }

    return `
      <td class="text-end">
        <div class="btn-group btn-group-sm">
          ${buttons.join('')}
        </div>
      </td>
    `;
  }

  static renderBadge(text: string, variant: 'primary' | 'secondary' | 'success' | 'warning' | 'danger' = 'secondary'): string {
    return `<span class="badge bg-${variant}-subtle text-${variant}">${text}</span>`;
  }
}

// Note: Classes are already exported individually above
