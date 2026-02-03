/**
 * Native Toast and Confirmation System
 *
 * Uses Alpine.js-powered components instead of SweetAlert2.
 * Components must be included in the page (see base.html.j2).
 */

interface ToastOptions {
  title: string;
  message: string;
  type: 'success' | 'error' | 'warning' | 'info';
  duration?: number;
}

interface ConfirmOptions {
  id?: string;
  title?: string;
  message?: string;
  type?: 'danger' | 'warning' | 'info' | 'success';
  confirmText?: string;
  cancelText?: string;
}

/**
 * Show a toast notification
 */
export function showToast({ title, message, type, duration = 3000 }: ToastOptions): void {
  window.dispatchEvent(
    new CustomEvent('toast', {
      detail: { title, message, type, duration },
    })
  );
}

/**
 * Show a confirmation dialog and return a Promise
 */
export function showConfirmation({
  id = `confirm-${Date.now()}`,
  title = 'Are you sure?',
  message = '',
  type = 'warning',
  confirmText = 'Confirm',
  cancelText = 'Cancel',
}: ConfirmOptions = {}): Promise<boolean> {
  return new Promise((resolve) => {
    const handler = (event: CustomEvent<{ id: string; confirmed: boolean }>) => {
      if (event.detail.id === id) {
        window.removeEventListener('confirm:result', handler as EventListener);
        resolve(event.detail.confirmed);
      }
    };

    window.addEventListener('confirm:result', handler as EventListener);

    window.dispatchEvent(
      new CustomEvent('confirm:show', {
        detail: { id, title, message, type, confirmText, cancelText },
      })
    );
  });
}

/**
 * Show a simple alert (uses toast for now)
 */
export function showAlert({
  title,
  message,
  type,
}: {
  title: string;
  message: string;
  type: 'success' | 'error' | 'warning' | 'info';
}): void {
  showToast({ title, message, type, duration: 5000 });
}

// Shorthand functions
export function showSuccess(message: string): void {
  showToast({ title: 'Success', message, type: 'success' });
}

export function showError(message: string): void {
  showToast({ title: 'Error', message, type: 'error' });
}

export function showWarning(message: string): void {
  showToast({ title: 'Warning', message, type: 'warning' });
}

export function showInfo(message: string): void {
  showToast({ title: 'Info', message, type: 'info' });
}

// Export for global access (used by Django messages)
if (typeof window !== 'undefined') {
  (window as Window & { showToast?: typeof showToast }).showToast = showToast;
}
