import { NotificationManager } from './utils/django-components';

// Expose Bootstrap notification functions globally
declare global {
  interface Window {
    showSuccess: (message: string) => void;
    showError: (message: string) => void;
    showWarning: (message: string) => void;
    showInfo: (message: string) => void;
  }
}

window.showSuccess = (message: string) => NotificationManager.showSuccess(message);
window.showError = (message: string) => NotificationManager.showError(message);
window.showWarning = (message: string) => NotificationManager.showWarning(message);
window.showInfo = (message: string) => NotificationManager.showSuccess(message); // Use success for info messages

export { NotificationManager };
