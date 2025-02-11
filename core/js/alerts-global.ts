import { showSuccess, showError, showWarning, showInfo } from './alerts';

// Expose alert functions globally
declare global {
  interface Window {
    showSuccess: typeof showSuccess;
    showError: typeof showError;
    showWarning: typeof showWarning;
    showInfo: typeof showInfo;
  }
}

window.showSuccess = showSuccess;
window.showError = showError;
window.showWarning = showWarning;
window.showInfo = showInfo;

export {};
