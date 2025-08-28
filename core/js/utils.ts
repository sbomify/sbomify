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
  const { NotificationManager } = await import('./utils/django-components');

  return await NotificationManager.showConfirmation(
    customMessage || `Are you sure you want to delete ${itemType} "${itemName}"? This action cannot be undone.`,
    'Delete Confirmation',
    'Delete',
    'Cancel'
  );
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
