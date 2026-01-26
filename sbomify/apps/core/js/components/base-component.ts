/**
 * Base Component Utilities
 * 
 * Provides reusable patterns and helpers for Alpine.js components
 */



/**
 * Base component interface for consistent structure
 */
export interface BaseComponent {
    $el: HTMLElement;
    init?: () => void;
    destroy?: () => void;
    // Internal property for HTMX listener tracking
    __htmxListeners?: Array<{ event: string; listener: EventListener }>;
}

/**
 * Helper to add HTMX lifecycle integration to an Alpine component
 * 
 * Automatically tracks and cleans up event listeners in the destroy method.
 */
export function withHTMXIntegration<T extends BaseComponent>(
    component: T,
    options: {
        onBeforeRequest?: (target: HTMLElement) => void;
        onAfterSwap?: (target: HTMLElement) => void;
        onAfterSettle?: (target: HTMLElement) => void;
        onError?: (target: HTMLElement, error: Error) => void;
    } = {}
): T {
    const originalInit = component.init || (() => { });
    const originalDestroy = component.destroy || (() => { });

    component.init = function (this: T) {
        originalInit.call(this);

        // Track listeners for cleanup (per component instance)
        const listeners: Array<{ event: string; listener: EventListener }> = [];

        // Set up HTMX event listeners and track them
        if (options.onBeforeRequest) {
            const listener = ((event: CustomEvent) => {
                const target = event.detail.elt as HTMLElement;
                if (this.$el.contains(target) || target === this.$el) {
                    options.onBeforeRequest!(target);
                }
            }) as EventListener;
            document.body.addEventListener('htmx:beforeRequest', listener);
            listeners.push({ event: 'htmx:beforeRequest', listener });
        }

        if (options.onAfterSwap) {
            const listener = ((event: CustomEvent) => {
                const target = event.detail.target as HTMLElement;
                if (this.$el.contains(target) || target === this.$el) {
                    options.onAfterSwap!(target);
                }
            }) as EventListener;
            document.body.addEventListener('htmx:afterSwap', listener);
            listeners.push({ event: 'htmx:afterSwap', listener });
        }

        if (options.onAfterSettle) {
            const listener = ((event: CustomEvent) => {
                const target = event.detail.target as HTMLElement;
                if (this.$el.contains(target) || target === this.$el) {
                    options.onAfterSettle!(target);
                }
            }) as EventListener;
            document.body.addEventListener('htmx:afterSettle', listener);
            listeners.push({ event: 'htmx:afterSettle', listener });
        }

        if (options.onError) {
            const listener = ((event: CustomEvent) => {
                const target = event.detail.target as HTMLElement;
                if (this.$el.contains(target) || target === this.$el) {
                    options.onError!(target, new Error('HTMX request failed'));
                }
            }) as EventListener;
            document.body.addEventListener('htmx:responseError', listener);
            listeners.push({ event: 'htmx:responseError', listener });
        }

        // Store listeners array on component for cleanup
        this.__htmxListeners = listeners;
    };

    component.destroy = function (this: T & BaseComponent) {
        // Cleanup all tracked HTMX listeners
        const componentListeners = this.__htmxListeners;
        if (componentListeners) {
            componentListeners.forEach(({ event, listener }) => {
                document.body.removeEventListener(event, listener);
            });
            this.__htmxListeners = undefined;
        }

        // Call original destroy
        originalDestroy.call(this);
    };

    return component;
}

/**
 * Helper to add debounce functionality to methods
 */
export function withDebounce<T extends Record<string, unknown>>(
    component: T,
    methodName: keyof T,
    delay: number = 300
): T {
    let timeoutId: ReturnType<typeof setTimeout> | null = null;
    const originalMethod = component[methodName] as (...args: unknown[]) => void;

    if (typeof originalMethod !== 'function') {
        return component;
    }

    component[methodName] = function (this: T, ...args: unknown[]) {
        if (timeoutId) {
            clearTimeout(timeoutId);
        }
        timeoutId = setTimeout(() => {
            originalMethod.apply(this, args);
            timeoutId = null;
        }, delay);
    } as T[keyof T];

    // Cleanup on destroy
    const originalDestroy = (component as { destroy?: () => void }).destroy || (() => { });
    (component as T & { destroy: () => void }).destroy = function (this: T) {
        if (timeoutId) {
            clearTimeout(timeoutId);
            timeoutId = null;
        }
        originalDestroy.call(this);
    };

    return component;
}

/**
 * Helper to add loading state management for async operations
 */
export function withLoadingState<T extends BaseComponent>(
    component: T & { loading?: boolean; error?: string | null }
): T & { loading: boolean; error: string | null; setLoading: (loading: boolean) => void; setError: (error: string | null) => void } {
    if (!component.loading) {
        component.loading = false;
    }
    if (component.error === undefined) {
        component.error = null;
    }

    (component as T & { setLoading: (loading: boolean) => void }).setLoading = function (this: typeof component, loading: boolean) {
        this.loading = loading;
    };

    (component as T & { setError: (error: string | null) => void }).setError = function (this: typeof component, error: string | null) {
        this.error = error;
    };

    return component as T & { loading: boolean; error: string | null; setLoading: (loading: boolean) => void; setError: (error: string | null) => void };
}

/**
 * Helper to wrap async operations with loading and error handling
 */
export async function withAsyncOperation<T extends BaseComponent & { loading?: boolean; error?: string | null; setLoading?: (loading: boolean) => void; setError?: (error: string | null) => void }>(
    component: T,
    operation: () => Promise<void>
): Promise<void> {
    if (component.setLoading) {
        component.setLoading(true);
    } else {
        component.loading = true;
    }

    if (component.setError) {
        component.setError(null);
    } else {
        component.error = null;
    }

    try {
        await operation();
    } catch (error) {
        const errorMessage = error instanceof Error ? error.message : 'An error occurred';
        if (component.setError) {
            component.setError(errorMessage);
        } else {
            component.error = errorMessage;
        }
        console.error('Async operation error:', error);
    } finally {
        if (component.setLoading) {
            component.setLoading(false);
        } else {
            component.loading = false;
        }
    }
}

/**
 * Helper to preserve Alpine state during HTMX swaps
 */
export function preserveAlpineState(element: HTMLElement): Record<string, unknown> {
    const state: Record<string, unknown> = {};
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const alpineData = (element as any)._x_dataStack;

    if (alpineData && alpineData.length > 0) {
        const data = alpineData[alpineData.length - 1];
        // Store non-function properties
        Object.keys(data).forEach(key => {
            if (typeof data[key] !== 'function' && !key.startsWith('$')) {
                state[key] = data[key];
            }
        });
    }

    return state;
}

/**
 * Helper to restore Alpine state after HTMX swap
 */
export function restoreAlpineState(element: HTMLElement, state: Record<string, unknown>): void {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const alpineData = (element as any)._x_dataStack;

    if (alpineData && alpineData.length > 0) {
        const data = alpineData[alpineData.length - 1];
        Object.keys(state).forEach(key => {
            if (data.hasOwnProperty(key)) {
                data[key] = state[key];
            }
        });
    }
}
