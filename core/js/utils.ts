import axios, { AxiosInstance } from "axios";
import Cookies from 'js-cookie';

const $axios = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
    'X-CSRFToken': Cookies.get('csrftoken') || '',
  },
});

export default $axios as AxiosInstance;

export function isEmpty(obj: unknown | string | number | object | null | undefined): boolean {
  if (typeof obj !== 'object' || obj === null) {
    return obj === undefined || obj === null || obj === '';
  }


  return Object.values(obj).every(value => {
    console.log(value);
    if (Array.isArray(value)) {
      return value.length === 0;
    } else {
      return value === null || value === '';
    }
  } );
}

export function getErrorMessage(error: Error | unknown): string {
  if (error instanceof Error) {
    return error.message;
  }
  return String(error);
}

export function formatDate(date: string | Date): string {
  return new Date(date).toLocaleDateString();
}

interface DeleteConfirmationOptions {
  itemName: string;
  itemType: string;
  customMessage?: string;
}

export async function confirmDelete({ itemName, itemType, customMessage }: DeleteConfirmationOptions): Promise<boolean> {
  const { default: Swal } = await import('sweetalert2');

  const result = await Swal.fire({
    title: 'Delete Confirmation',
    text: customMessage || `Are you sure you want to delete ${itemType} "${itemName}"? This action cannot be undone.`,
    icon: 'warning',
    showCancelButton: true,
    confirmButtonText: 'Delete',
    cancelButtonText: 'Cancel',
    confirmButtonColor: '#dc3545', // Bootstrap danger color
    cancelButtonColor: '#6c757d',  // Bootstrap secondary color
    focusCancel: true, // Safer default
    customClass: {
      confirmButton: 'btn btn-danger',
      cancelButton: 'btn btn-secondary',
      actions: 'gap-2' // Add gap between buttons
    },
    buttonsStyling: false,
    reverseButtons: true // Cancel on left, Delete on right
  });

  return result.isConfirmed;
}
