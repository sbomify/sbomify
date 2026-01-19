import { showSuccess, showError, showWarning, showInfo, showToast, showConfirmation } from './alerts';

// Expose alert functions globally
declare global {
  interface Window {
    showSuccess: typeof showSuccess;
    showError: typeof showError;
    showWarning: typeof showWarning;
    showInfo: typeof showInfo;
    showToast: typeof showToast;
    showConfirmation: typeof showConfirmation;
  }
}

window.showSuccess = showSuccess;
window.showError = showError;
window.showWarning = showWarning;
window.showInfo = showInfo;
window.showToast = showToast;
window.showConfirmation = showConfirmation;

export { showToast, showSuccess, showError, showWarning, showInfo, showConfirmation };
