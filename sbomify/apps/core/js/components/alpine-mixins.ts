/**
 * Alpine.js Mixins
 * 
 * Reusable mixins for common component patterns
 */

/**
 * Fetch mixin - For API calls with loading/error states
 */
export function fetchMixin() {
    return {
        loading: false,
        error: null as string | null,

        async fetchData(url: string, options: RequestInit = {}): Promise<unknown> {
            this.loading = true;
            this.error = null;

            try {
                const response = await fetch(url, {
                    ...options,
                    headers: {
                        'X-Requested-With': 'XMLHttpRequest',
                        ...options.headers,
                    },
                });

                if (!response.ok) {
                    throw new Error(`Request failed: ${response.status}`);
                }

                const data = await response.json();
                this.loading = false;
                return data;
            } catch (error) {
                this.error = error instanceof Error ? error.message : 'An error occurred';
                this.loading = false;
                throw error;
            }
        },

        get hasError(): boolean {
            return this.error !== null;
        },

        clearError(): void {
            this.error = null;
        }
    };
}

/**
 * Modal mixin - For modal open/close state
 */
export function modalMixin(initialOpen: boolean = false) {
    return {
        isOpen: initialOpen,

        open(): void {
            this.isOpen = true;
        },

        close(): void {
            this.isOpen = false;
        },

        toggle(): void {
            this.isOpen = !this.isOpen;
        }
    };
}

/**
 * Get CSRF token from cookies for Django CSRF protection
 */
function getCsrfToken(): string {
    const cookieValue = document.cookie
        .split('; ')
        .find(row => row.startsWith('csrftoken='))
        ?.split('=')[1] || '';
    return cookieValue;
}

/**
 * Form mixin - For form validation and submission
 */
export function formMixin() {
    return {
        submitting: false,
        errors: {} as Record<string, string>,
        touched: {} as Record<string, boolean>,

        setError(field: string, message: string): void {
            this.errors[field] = message;
            this.touched[field] = true;
        },

        clearError(field: string): void {
            delete this.errors[field];
        },

        clearAllErrors(): void {
            this.errors = {};
            this.touched = {};
        },

        get hasErrors(): boolean {
            return Object.keys(this.errors).length > 0;
        },

        getFieldError(field: string): string | undefined {
            return this.errors[field];
        },

        isFieldTouched(field: string): boolean {
            return this.touched[field] === true;
        },

        touchField(field: string): void {
            this.touched[field] = true;
        },

        async submitForm(url: string, formData: FormData, options: RequestInit = {}): Promise<unknown> {
            this.submitting = true;
            this.clearAllErrors();

            try {
                const response = await fetch(url, {
                    method: 'POST',
                    body: formData,
                    headers: {
                        'X-Requested-With': 'XMLHttpRequest',
                        'X-CSRFToken': getCsrfToken(),
                        ...options.headers,
                    },
                    ...options,
                });

                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({}));
                    if (errorData.errors) {
                        Object.keys(errorData.errors).forEach(field => {
                            this.setError(field, errorData.errors[field]);
                        });
                    } else {
                        this.setError('_form', 'Form submission failed');
                    }
                    this.submitting = false;
                    return null;
                }

                const data = await response.json();
                this.submitting = false;
                return data;
            } catch (error) {
                this.setError('_form', error instanceof Error ? error.message : 'An error occurred');
                this.submitting = false;
                throw error;
            }
        }
    };
}

/**
 * Dropdown mixin - For dropdown state management
 * Note: $el is injected by Alpine.js at runtime
 */
interface DropdownMixinThis {
    $el: HTMLElement;
    isOpen: boolean;
    close(): void;
}

export function dropdownMixin(initialOpen: boolean = false) {
    return {
        isOpen: initialOpen,

        open(): void {
            this.isOpen = true;
        },

        close(): void {
            this.isOpen = false;
        },

        toggle(): void {
            this.isOpen = !this.isOpen;
        },

        handleClickOutside(this: DropdownMixinThis, event: MouseEvent): void {
            const target = event.target as HTMLElement;
            if (!this.$el.contains(target)) {
                this.close();
            }
        },

        handleEscape(this: DropdownMixinThis, event: KeyboardEvent): void {
            if (event.key === 'Escape' && this.isOpen) {
                this.close();
            }
        }
    };
}

/**
 * Debounce mixin - For debounced methods
 */
export function debounceMixin() {
    return {
        debounceTimeouts: {} as Record<string, ReturnType<typeof setTimeout>>,

        debounce(methodName: string, callback: () => void, delay: number = 300): void {
            if (this.debounceTimeouts[methodName]) {
                clearTimeout(this.debounceTimeouts[methodName]);
            }

            this.debounceTimeouts[methodName] = setTimeout(() => {
                callback();
                delete this.debounceTimeouts[methodName];
            }, delay);
        },

        clearDebounce(methodName?: string): void {
            if (methodName) {
                if (this.debounceTimeouts[methodName]) {
                    clearTimeout(this.debounceTimeouts[methodName]);
                    delete this.debounceTimeouts[methodName];
                }
            } else {
                Object.values(this.debounceTimeouts).forEach(timeout => clearTimeout(timeout));
                this.debounceTimeouts = {};
            }
        },

        destroy(): void {
            this.clearDebounce();
        }
    };
}

/**
 * Local storage mixin - For persisting state to localStorage
 */
export function persistMixin(key: string) {
    return {
        persistKey: key,

        save(data: unknown): void {
            try {
                localStorage.setItem(this.persistKey, JSON.stringify(data));
            } catch (error) {
                console.error('Failed to save to localStorage:', error);
            }
        },

        load(): unknown {
            try {
                const item = localStorage.getItem(this.persistKey);
                return item ? JSON.parse(item) : null;
            } catch (error) {
                console.error('Failed to load from localStorage:', error);
                return null;
            }
        },

        clear(): void {
            try {
                localStorage.removeItem(this.persistKey);
            } catch (error) {
                console.error('Failed to clear localStorage:', error);
            }
        }
    };
}
