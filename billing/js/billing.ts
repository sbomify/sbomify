import Swal from 'sweetalert2';

// Function to show success message
export function showSuccessMessage(message: string) {
    Swal.fire({
        title: 'Success',
        text: message,
        icon: 'success',
        toast: true,
        position: 'top-end',
        showConfirmButton: false,
        timer: 3000,
        timerProgressBar: true
    });
}

// Function to show error message
export function showErrorMessage(message: string) {
    Swal.fire({
        title: 'Error',
        text: message,
        icon: 'error',
        toast: true,
        position: 'top-end',
        showConfirmButton: false,
        timer: 3000,
        timerProgressBar: true
    });
}

// Initialize billing notifications
document.addEventListener('DOMContentLoaded', () => {
    // Check for flash messages in the DOM
    const messages = document.querySelectorAll('[data-flash-message]');
    messages.forEach(messageElement => {
        const message = messageElement.textContent;
        const type = messageElement.getAttribute('data-message-type');

        if (type === 'error') {
            showErrorMessage(message || '');
        } else {
            showSuccessMessage(message || '');
        }

        // Remove the message element
        messageElement.remove();
    });
});