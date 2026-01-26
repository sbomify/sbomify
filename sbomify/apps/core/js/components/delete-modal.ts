import Alpine from 'alpinejs';
import { showSuccess, showError } from '../alerts';

interface DeleteModalConfig {
    modalId: string;
    hxUrl: string;
    hxMethod?: string;
    successMessage: string;
    csrfToken: string;
    redirectUrl?: string;
    refreshEvent?: string;
}

interface DeleteModalData {
    isLoading: boolean;
    getCsrfToken(): string;
    handleDelete(): Promise<void>;
    [key: string]: boolean | (() => string) | (() => Promise<void>);
}

declare global {
    interface Window {
        getDeleteModalData: (config: DeleteModalConfig) => DeleteModalData;
        handleTabKey: (event: KeyboardEvent) => void; // For templates - uses $store.modals internally
        handleModalOpen: (modalElement: HTMLElement, modalId: string) => void; // For templates - uses $store.modals internally
        handleModalClose: (modalId: string) => void; // For templates - uses $store.modals internally
        initDeleteModal: (modalId: string, overlay: HTMLElement) => void; // For templates - uses $store.modals internally
    }
}

export function registerDeleteModal(): void {
    // Get modals store - use store methods when available, fallback to window globals for backward compatibility
    const getModalsStore = (): { handleTabKey?: (event: KeyboardEvent, modalElement: HTMLElement) => void; handleModalOpen?: (modalElement: HTMLElement, modalId: string) => void; handleModalClose?: (modalId: string) => void; initModal?: (modalId: string, overlay: HTMLElement) => void } | null => {
        try {
            return Alpine.store('modals') as { handleTabKey?: (event: KeyboardEvent, modalElement: HTMLElement) => void; handleModalOpen?: (modalElement: HTMLElement, modalId: string) => void; handleModalClose?: (modalId: string) => void; initModal?: (modalId: string, overlay: HTMLElement) => void };
        } catch {
            return null;
        }
    };

    // Make functions available globally for templates (templates use window functions)
    // Prefer using $store.modals.* in Alpine components
    if (typeof window.handleTabKey === 'undefined') {
        window.handleTabKey = function (event: KeyboardEvent) {
            const modalElement = event.currentTarget as HTMLElement;
            if (modalElement) {
                const store = getModalsStore();
                if (store && store.handleTabKey) {
                    store.handleTabKey(event, modalElement);
                }
            }
        };
    }

    if (typeof window.handleModalOpen === 'undefined') {
        window.handleModalOpen = function (modalElement: HTMLElement, modalId: string) {
            const store = getModalsStore();
            if (store && store.handleModalOpen) {
                store.handleModalOpen(modalElement, modalId);
            }
        };
    }

    if (typeof window.handleModalClose === 'undefined') {
        window.handleModalClose = function (modalId: string) {
            const store = getModalsStore();
            if (store && store.handleModalClose) {
                store.handleModalClose(modalId);
            }
        };
    }

    // showSuccess and showError are imported directly - no window globals needed

    if (!window.getDeleteModalData) {
        window.getDeleteModalData = function (config: DeleteModalConfig) {
            return {
                isLoading: false,
                getCsrfToken() {
                    // Priority 1: Use token passed from Django template
                    if (config.csrfToken && config.csrfToken.trim()) {
                        return config.csrfToken.trim();
                    }

                    // Priority 2: Try to get from meta tag (if Django provides it)
                    const metaToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content');
                    if (metaToken && metaToken.trim()) {
                        return metaToken.trim();
                    }

                    // Priority 3: Fallback to cookie parsing with better error handling
                    try {
                        if (!document.cookie) {
                            console.warn('No cookies available');
                            return '';
                        }

                        const cookies = document.cookie.split(';');
                        for (let i = 0; i < cookies.length; i++) {
                            const cookie = cookies[i].trim();
                            // Handle both 'csrftoken=' and 'csrftoken =' (with spaces)
                            if (cookie.startsWith('csrftoken')) {
                                const parts = cookie.split('=');
                                if (parts.length >= 2) {
                                    // Join all parts after the first '=' in case the token contains '='
                                    const token = parts.slice(1).join('=');
                                    if (token && token.trim()) {
                                        return decodeURIComponent(token.trim());
                                    }
                                }
                            }
                        }
                    } catch (error) {
                        console.error('Error parsing CSRF token from cookies:', error);
                    }

                    return '';
                },
                async handleDelete() {
                    if (this.isLoading) return;
                    this.isLoading = true;

                    const csrfToken = this.getCsrfToken();

                    if (!csrfToken) {
                        this.isLoading = false;
                        const errorMsg = 'Security error: Missing CSRF token. Please reload the page and try again.';
                        console.error(errorMsg);
                        showError(errorMsg); // Use imported function
                        this[config.modalId] = false;
                        return;
                    }

                    try {
                        const response = await fetch(config.hxUrl, {
                            method: config.hxMethod || 'DELETE',
                            headers: {
                                'Content-Type': 'application/json',
                                'X-CSRFToken': csrfToken
                            },
                            credentials: 'same-origin'
                        });

                        if (response.ok) {
                            showSuccess(config.successMessage); // Use imported function
                            this[config.modalId] = false;
                            if (config.redirectUrl) {
                                window.location.href = config.redirectUrl;
                            } else if (config.refreshEvent) {
                                // Dispatch custom event to trigger HTMX refresh
                                document.body.dispatchEvent(new CustomEvent(config.refreshEvent));
                            }
                        } else {
                            let errorDetail = '';
                            try {
                                const contentType = response.headers.get('Content-Type') || '';

                                if (contentType.includes('application/json')) {
                                    const data = await response.json() as { detail?: string } | Record<string, unknown>;
                                    if (data) {
                                        if (typeof data.detail === 'string') {
                                            errorDetail = data.detail;
                                        } else {
                                            errorDetail = JSON.stringify(data);
                                        }
                                    }
                                } else {
                                    errorDetail = await response.text();
                                }
                            } catch (parseError) {
                                console.error('Failed to parse error response body:', parseError);
                            }

                            if (errorDetail) {
                                console.error('Delete failed:', response.status, errorDetail);
                                showError(`Failed to delete: ${errorDetail}`); // Use imported function
                            } else {
                                console.error('Delete failed:', response.status);
                                showError('Failed to delete. Please try again.'); // Use imported function
                            }
                            this[config.modalId] = false;
                        }
                    } catch (error) {
                        console.error('Delete error:', error);
                        showError('An error occurred. Please try again.'); // Use imported function
                        this[config.modalId] = false;
                    } finally {
                        this.isLoading = false;
                    }
                }
            };
        };
    }

    if (!window.initDeleteModal) {
        window.initDeleteModal = function (modalId: string, overlay: HTMLElement) {
            const store = getModalsStore();
            if (store && store.initModal) {
                // Use store method
                store.initModal(modalId, overlay);
            } else {
                // Fallback to old implementation (should not happen if store is initialized)
                console.warn('Modals store not available, using fallback');
            }
        };
    }

    // Alpine component for Bootstrap delete modal with form field population
    Alpine.data('bootstrapDeleteModal', (modalId: string) => {
        return {
            modalId,
            modalOpen: false, // Track modal open state for x-trap focus management
            
            init() {
                // Ensure modal is appended to body if needed
                if (this.$el.parentElement !== document.body) {
                    document.body.appendChild(this.$el);
                    // Process HTMX if available
                    if (typeof (window as { htmx?: { process: (el: HTMLElement) => void } }).htmx !== 'undefined') {
                        (window as unknown as { htmx: { process: (el: HTMLElement) => void } }).htmx.process(this.$el);
                    }
                }
            },
            
            open(button?: HTMLElement) {
                this.modalOpen = true;
                
                if (!button) {
                    // Try to find the button that triggered this (from event)
                    const event = (window as { lastModalEvent?: Event }).lastModalEvent;
                    if (event && event.target) {
                        button = event.target as HTMLElement;
                    }
                }
                
                if (!button) return;
                
                const form = (this.$refs as { form?: HTMLFormElement }).form;
                const displayName = (this.$refs as { displayName?: HTMLElement }).displayName;
                
                if (!form) return;
                
                // Populate form fields from data-form-* attributes
                Array.from(button.attributes).forEach(attr => {
                    if (!attr.name.startsWith('data-form-')) {
                        return;
                    }
                    
                    const fieldName = attr.name.replace('data-form-', '');
                    const field = form.querySelector(`[name="${fieldName}"]`) as HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement;
                    
                    if (field) {
                        field.value = attr.value;
                    }
                });
                
                // Set display name if provided
                if (displayName) {
                    const displayNameValue = button.getAttribute('data-display-name');
                    if (displayNameValue) {
                        displayName.textContent = displayNameValue;
                    }
                }
            },
            
            close() {
                this.modalOpen = false;
            },
            
            // Legacy handler for Bootstrap events (if any remain)
            handleShow(event: Event) {
                (window as { lastModalEvent?: Event }).lastModalEvent = event;
                const bootstrapEvent = event as CustomEvent & { relatedTarget?: HTMLElement };
                this.open(bootstrapEvent.relatedTarget || undefined);
            }
        };
    });
}
