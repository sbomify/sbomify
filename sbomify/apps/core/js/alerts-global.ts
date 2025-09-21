import { showSuccess, showError, showWarning, showInfo, showToast } from './alerts';

// Expose alert functions globally
declare global {
  interface Window {
    showSuccess: typeof showSuccess;
    showError: typeof showError;
    showWarning: typeof showWarning;
    showInfo: typeof showInfo;
    showToast: typeof showToast;
  }
}

window.showSuccess = showSuccess;
window.showError = showError;
window.showWarning = showWarning;
window.showInfo = showInfo;
window.showToast = showToast;

export { showToast, showSuccess, showError, showWarning, showInfo };
