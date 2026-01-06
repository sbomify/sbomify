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
    if (Array.isArray(value)) {
      return value.length === 0;
    } else {
      return value === null || value === '';
    }
  });
}

/**
 * Parse JSON from a script tag by ID. Returns null if not found, empty, or invalid.
 * Use with Django's json_script filter: {{ data|json_script:"my-id" }}
 */
export function parseJsonScript<T = unknown>(elementId: string): T | null {
  const scriptEl = document.getElementById(elementId);
  if (!scriptEl?.textContent || scriptEl.textContent === 'null') {
    return null;
  }
  try {
    return JSON.parse(scriptEl.textContent) as T;
  } catch {
    return null;
  }
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

/**
 * Simple event emitter for cross-component communication
 * Replaces global window function dependencies
 */
type EventCallback = (...args: unknown[]) => void;

class EventEmitter {
  private events: Record<string, EventCallback[]> = {};

  on(event: string, callback: EventCallback): void {
    if (!this.events[event]) {
      this.events[event] = [];
    }
    this.events[event].push(callback);
  }

  off(event: string, callback: EventCallback): void {
    if (!this.events[event]) return;

    const index = this.events[event].indexOf(callback);
    if (index > -1) {
      this.events[event].splice(index, 1);
    }
  }

  emit(event: string, ...args: unknown[]): void {
    if (!this.events[event]) return;

    this.events[event].forEach(callback => {
      try {
        callback(...args);
      } catch (error) {
        console.error(`Error in event listener for ${event}:`, error);
      }
    });
  }
}

// Global event emitter instance
export const eventBus = new EventEmitter();

// Event constants
export const EVENTS = {
  REFRESH_PRODUCTS: 'refresh_products',
  REFRESH_PROJECTS: 'refresh_projects',
  REFRESH_COMPONENTS: 'refresh_components',
  ITEM_CREATED: 'item_created',
  ITEM_UPDATED: 'item_updated',
  ITEM_DELETED: 'item_deleted',
} as const;
