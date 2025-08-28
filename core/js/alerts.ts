import { NotificationManager } from './utils/django-components';

interface ToastOptions {
  title: string;
  message: string;
  type: 'success' | 'error' | 'warning' | 'info';
  timer?: number;
  position?: 'top-end' | 'top' | 'top-start' | 'center' | 'bottom' | 'bottom-end' | 'bottom-start';
}

interface AlertOptions {
  title: string;
  message: string;
  type: 'success' | 'error' | 'warning' | 'info';
  showCancelButton?: boolean;
  confirmButtonText?: string;
  cancelButtonText?: string;
  customClass?: {
    confirmButton?: string;
    cancelButton?: string;
    actions?: string;
  };
}

// Toast notifications for non-blocking messages
export function showToast({
  message,
  type
}: Pick<ToastOptions, 'message' | 'type'>) {
  // Use Bootstrap toast instead
  switch(type) {
    case 'success':
      NotificationManager.showSuccess(message);
      break;
    case 'error':
      NotificationManager.showError(message);
      break;
    case 'warning':
      NotificationManager.showWarning(message);
      break;
    case 'info':
      NotificationManager.showSuccess(message); // Use success for info messages
      break;
  }
}

// Modal alerts for important messages that require attention
export function showAlert({
  title,
  message
}: Pick<AlertOptions, 'title' | 'message'>) {
  // Use Bootstrap modal instead
  return NotificationManager.showConfirmation(message, title, 'OK', 'Cancel');
}

// Confirmation dialog for destructive actions
export async function showConfirmation({
  title = 'Are you sure?',
  message,
  confirmButtonText = 'Yes',
  cancelButtonText = 'No'
}: Partial<Pick<AlertOptions, 'title' | 'message' | 'confirmButtonText' | 'cancelButtonText'>>) {
  if (!message) {
    throw new Error('Message is required for confirmation dialog');
  }
  return await NotificationManager.showConfirmation(message, title, confirmButtonText, cancelButtonText);
}

// Success toast shorthand
export function showSuccess(message: string) {
  NotificationManager.showSuccess(message);
}

// Error toast shorthand
export function showError(message: string) {
  NotificationManager.showError(message);
}

// Warning toast shorthand
export function showWarning(message: string) {
  NotificationManager.showWarning(message);
}

// Info toast shorthand
export function showInfo(message: string) {
  NotificationManager.showSuccess(message); // Use success for info messages
}