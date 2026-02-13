import axios, { AxiosHeaders, AxiosInstance } from "axios";
import { getCsrfToken } from './csrf';

const $axios = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL,
  withCredentials: true,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Add CSRF token to requests dynamically via interceptor
$axios.interceptors.request.use((config) => {
  try {
    const token = getCsrfToken();
    if (!config.headers) {
      config.headers = new AxiosHeaders();
    }
    config.headers.set('X-CSRFToken', token);
  } catch {
    // CSRF token not available, let the request proceed without it
    // Server will return 403 if CSRF is required
  }
  return config;
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

/**
 * Parse a date value, returning null for anything invalid.
 */
function parseDate(value: string | Date | null | undefined): Date | null {
  if (value == null || value === '') return null;
  const d = value instanceof Date ? value : new Date(value);
  return isNaN(d.getTime()) ? null : d;
}

const SHORT_DATE_OPTS: Intl.DateTimeFormatOptions = {
  year: 'numeric', month: 'short', day: 'numeric',
};

/**
 * Locale-aware short date: "Feb 13, 2026"
 */
export function formatDate(
  value?: string | Date | null,
  opts?: { fallback?: string },
): string {
  const d = parseDate(value);
  if (!d) return opts?.fallback ?? '-';
  return d.toLocaleDateString(undefined, SHORT_DATE_OPTS);
}

/**
 * Locale-aware date + time: "Feb 13, 2026, 3:45 PM"
 */
export function formatDateTime(
  value?: string | Date | null,
  opts?: { use24Hour?: boolean; fallback?: string },
): string {
  const d = parseDate(value);
  if (!d) return opts?.fallback ?? '-';
  return d.toLocaleString(undefined, {
    ...SHORT_DATE_OPTS,
    hour: 'numeric',
    minute: '2-digit',
    hour12: !(opts?.use24Hour),
  });
}

/**
 * Relative date for recent items: "Today" / "yesterday" / "3 days ago" / absolute.
 * Falls back to absolute date after 7 days.
 */
export function formatRelativeDate(
  value?: string | Date | null,
  opts?: { now?: Date; fallback?: string },
): string {
  const d = parseDate(value);
  if (!d) return opts?.fallback ?? '-';
  const now = opts?.now ?? new Date();

  const isToday =
    d.getDate() === now.getDate() &&
    d.getMonth() === now.getMonth() &&
    d.getFullYear() === now.getFullYear();
  if (isToday) return 'Today';

  const diffDays = Math.floor((now.getTime() - d.getTime()) / 86_400_000);

  if (diffDays > 7) {
    return d.toLocaleDateString(undefined, SHORT_DATE_OPTS);
  }

  const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' });
  return rtf.format(-diffDays, 'day');
}

/**
 * Compact relative date for notifications: "Just now" / "5m ago" / "2h ago" / "3d ago".
 * Falls back to absolute date after 7 days.
 */
export function formatCompactRelativeDate(
  value?: string | Date | null,
  opts?: { now?: Date; fallback?: string },
): string {
  const d = parseDate(value);
  if (!d) return opts?.fallback ?? '-';
  const now = opts?.now ?? new Date();
  const diffMs = now.getTime() - d.getTime();
  const diffMins = Math.floor(diffMs / 60_000);
  const diffHours = Math.floor(diffMs / 3_600_000);
  const diffDays = Math.floor(diffMs / 86_400_000);

  if (diffMins < 1) return 'Just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;
  return d.toLocaleDateString(undefined, SHORT_DATE_OPTS);
}

/**
 * For "last checked" displays: returns "Never" for missing values.
 */
export function formatLastChecked(
  value?: string | Date | null,
  opts?: { fallback?: string },
): string {
  const d = parseDate(value);
  if (!d) return opts?.fallback ?? 'Never';
  return d.toLocaleString(undefined, {
    ...SHORT_DATE_OPTS,
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  });
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
