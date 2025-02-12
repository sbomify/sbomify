import Swal from 'sweetalert2';

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
  title,
  message,
  type,
  timer = 3000,
  position = 'top-end'
}: ToastOptions) {
  return Swal.fire({
    title,
    text: message,
    icon: type,
    toast: true,
    position,
    showConfirmButton: false,
    timer,
    timerProgressBar: true,
    customClass: {
      popup: 'swal2-toast'
    }
  });
}

// Modal alerts for important messages that require attention
export function showAlert({
  title,
  message,
  type,
  showCancelButton = false,
  confirmButtonText = 'OK',
  cancelButtonText = 'Cancel',
  customClass = {
    confirmButton: 'btn btn-primary',
    cancelButton: 'btn btn-secondary',
    actions: 'gap-2'
  }
}: AlertOptions) {
  return Swal.fire({
    title,
    text: message,
    icon: type,
    showCancelButton,
    confirmButtonText,
    cancelButtonText,
    customClass,
    buttonsStyling: false,
    reverseButtons: true
  });
}

// Confirmation dialog for destructive actions
export async function showConfirmation({
  title = 'Are you sure?',
  message,
  confirmButtonText = 'Yes',
  cancelButtonText = 'No',
  type = 'warning'
}: Partial<AlertOptions>) {
  const result = await Swal.fire({
    title,
    text: message,
    icon: type,
    showCancelButton: true,
    confirmButtonText,
    cancelButtonText,
    customClass: {
      confirmButton: 'btn btn-danger',
      cancelButton: 'btn btn-secondary',
      actions: 'gap-2'
    },
    buttonsStyling: false,
    reverseButtons: true,
    focusCancel: true
  });

  return result.isConfirmed;
}

// Success toast shorthand
export function showSuccess(message: string) {
  return showToast({
    title: 'Success',
    message,
    type: 'success'
  });
}

// Error toast shorthand
export function showError(message: string) {
  return showToast({
    title: 'Error',
    message,
    type: 'error'
  });
}

// Warning toast shorthand
export function showWarning(message: string) {
  return showToast({
    title: 'Warning',
    message,
    type: 'warning'
  });
}

// Info toast shorthand
export function showInfo(message: string) {
  return showToast({
    title: 'Info',
    message,
    type: 'info'
  });
}