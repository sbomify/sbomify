import { showToast, showConfirmation } from './alerts';

// Expose alert functions globally
declare global {
  interface Window {
    showToast: typeof showToast;
    showConfirmation: typeof showConfirmation;
  }
}

window.showToast = showToast;
window.showConfirmation = showConfirmation;
