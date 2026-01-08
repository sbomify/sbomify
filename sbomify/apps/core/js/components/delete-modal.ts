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

interface ModalFocusTrap {
    triggerElements: Record<string, HTMLElement>;
    getFocusableElements(container: HTMLElement): HTMLElement[];
    handleTabKey(event: KeyboardEvent, modalElement: HTMLElement): void;
    handleModalOpen(modalElement: HTMLElement, modalId: string): void;
    handleModalClose(modalId: string): void;
}

interface ModalObservers {
    intersectionObserver: IntersectionObserver;
    mutationObserver: MutationObserver;
}

declare global {
    interface Window {
        getDeleteModalData: (config: DeleteModalConfig) => DeleteModalData;
        modalFocusTrap: ModalFocusTrap;
        handleTabKey: (event: KeyboardEvent) => void;
        handleModalOpen: (modalElement: HTMLElement, modalId: string) => void;
        handleModalClose: (modalId: string) => void;
        initDeleteModal: (modalId: string, overlay: HTMLElement) => void;
        modalObservers: Map<string, ModalObservers>;
    }
}

export function registerDeleteModal() {
    // Timeout constants for focus management
    // These delays allow the DOM to update and ensure focus operations work correctly
    const FOCUS_DELAY_MS = 50; // Delay for focusing elements after modal opens (allows DOM updates)
    const FOCUS_RETURN_DELAY_MS = 100; // Delay for returning focus after modal closes (ensures modal is fully closed)
    const INITIAL_CHECK_DELAY_MS = 150; // Delay for initial visibility check (allows Alpine.js to finish rendering)

    // Focus trapping utilities for modal accessibility
    if (!window.modalFocusTrap) {
        window.modalFocusTrap = {
            // Store the element that triggered the modal
            triggerElements: {} as Record<string, HTMLElement>,

            // Get all focusable elements within a container
            getFocusableElements(container: HTMLElement) {
                const focusableSelectors = [
                    'a[href]',
                    'button:not([disabled])',
                    'textarea:not([disabled])',
                    'input:not([disabled])',
                    'select:not([disabled])',
                    '[tabindex]:not([tabindex="-1"])'
                ].join(', ');

                return Array.from(container.querySelectorAll<HTMLElement>(focusableSelectors))
                    .filter(el => {
                        // Filter out elements that are not visible
                        const style = window.getComputedStyle(el);
                        return style.display !== 'none' &&
                            style.visibility !== 'hidden' &&
                            !el.hasAttribute('disabled');
                    });
            },

            // Handle Tab key navigation with focus trapping
            handleTabKey(event: KeyboardEvent, modalElement: HTMLElement) {
                // Find the modal content (not the overlay)
                const modalContent = modalElement.querySelector<HTMLElement>('.delete-modal');
                if (!modalContent) {
                    event.preventDefault();
                    return;
                }

                const focusableElements = this.getFocusableElements(modalContent);

                if (focusableElements.length === 0) {
                    event.preventDefault();
                    return;
                }

                const firstElement = focusableElements[0];
                const lastElement = focusableElements[focusableElements.length - 1];
                const currentElement = document.activeElement as HTMLElement;

                // Check if current focus is within the modal
                if (!modalContent.contains(currentElement)) {
                    // Focus is outside modal, move to first element
                    event.preventDefault();
                    firstElement.focus();
                    return;
                }

                // If Shift+Tab on first element, move to last
                if (event.shiftKey && currentElement === firstElement) {
                    event.preventDefault();
                    lastElement.focus();
                }
                // If Tab on last element, move to first
                else if (!event.shiftKey && currentElement === lastElement) {
                    event.preventDefault();
                    firstElement.focus();
                }
            },

            // Handle modal opening - focus first element and store trigger
            handleModalOpen(modalElement: HTMLElement, modalId: string) {
                // Store the currently focused element as the trigger
                if (document.activeElement &&
                    document.activeElement !== document.body &&
                    !modalElement.contains(document.activeElement)) {
                    this.triggerElements[modalId] = document.activeElement as HTMLElement;
                }

                // Find the modal content (not the overlay)
                const modalContent = modalElement.querySelector<HTMLElement>('.delete-modal');
                if (!modalContent) return;

                // Get focusable elements
                const focusableElements = this.getFocusableElements(modalContent);

                if (focusableElements.length > 0) {
                    // Prefer focusing the close button, then cancel button, then first available
                    const closeButton = modalContent.querySelector<HTMLElement>('.delete-modal-close');
                    const cancelButton = modalContent.querySelector<HTMLElement>('.delete-modal-button--secondary');

                    let elementToFocus: HTMLElement | null = null;
                    if (closeButton && focusableElements.includes(closeButton)) {
                        elementToFocus = closeButton;
                    } else if (cancelButton && focusableElements.includes(cancelButton)) {
                        elementToFocus = cancelButton;
                    } else {
                        elementToFocus = focusableElements[0];
                    }

                    // Focus the selected element
                    setTimeout(() => {
                        elementToFocus?.focus();
                    }, FOCUS_DELAY_MS);
                } else {
                    // If no focusable elements, focus the modal content itself
                    modalContent.setAttribute('tabindex', '-1');
                    setTimeout(() => {
                        modalContent.focus();
                    }, FOCUS_DELAY_MS);
                }
            },

            // Handle modal closing - return focus to trigger element
            handleModalClose(modalId: string) {
                const triggerElement = this.triggerElements[modalId];
                if (triggerElement && triggerElement.focus) {
                    // Use setTimeout to ensure modal is fully closed before focusing
                    setTimeout(() => {
                        try {
                            triggerElement.focus();
                        } catch (e) {
                            // Element might not be focusable anymore, ignore
                            console.warn('Could not return focus to trigger element:', e);
                        }
                    }, FOCUS_RETURN_DELAY_MS);
                }
                // Clean up
                delete this.triggerElements[modalId];
            }
        };
    }

    // Make functions available globally for Alpine.js
    if (typeof window.handleTabKey === 'undefined') {
        window.handleTabKey = function (event: KeyboardEvent) {
            // Check if currentTarget is an HTMLElement
            const modalElement = event.currentTarget as HTMLElement;
            if (modalElement) {
                window.modalFocusTrap.handleTabKey(event, modalElement);
            }
        };
    }

    if (typeof window.handleModalOpen === 'undefined') {
        window.handleModalOpen = function (modalElement: HTMLElement, modalId: string) {
            window.modalFocusTrap.handleModalOpen(modalElement, modalId);
        };
    }

    if (typeof window.handleModalClose === 'undefined') {
        window.handleModalClose = function (modalId: string) {
            window.modalFocusTrap.handleModalClose(modalId);
        };
    }

    // Fallback for showSuccess and showError is NOT needed here because we import them.
    // But we might want to ensure they are on window if the template relies on them being on window from elsewhere.
    // But the template doesn't call window.showSuccess directly unless via our code or existing pattern.
    // main.ts sets them on window via alerts-global.ts so we are good.

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

    // Initialize observers storage
    if (!window.modalObservers) {
        window.modalObservers = new Map<string, ModalObservers>();
    }

    if (!window.initDeleteModal) {
        window.initDeleteModal = function (modalId: string, overlay: HTMLElement) {
            // Disconnect existing observers for this modal if they exist
            const existingObservers = window.modalObservers.get(modalId);
            if (existingObservers) {
                existingObservers.intersectionObserver.disconnect();
                existingObservers.mutationObserver.disconnect();
                window.modalObservers.delete(modalId);
            }

            let wasVisible = false;
            let isProcessing = false;

            // Consolidated visibility check function to prevent race conditions
            const checkVisibility = () => {
                if (isProcessing) return; // Prevent concurrent execution
                isProcessing = true;

                const isVisible = window.getComputedStyle(overlay).display !== 'none';

                if (isVisible && !wasVisible) {
                    // Modal just opened
                    wasVisible = true;
                    window.handleModalOpen(overlay, modalId);
                } else if (!isVisible && wasVisible) {
                    // Modal just closed
                    wasVisible = false;
                    window.handleModalClose(modalId);
                }

                isProcessing = false;
            };

            // Watch for visibility changes using IntersectionObserver
            // Note: Alpine.js x-show controls visibility via display property, so we only check computed style
            // eslint-disable-next-line @typescript-eslint/no-unused-vars
            const observer = new IntersectionObserver((_entries) => {
                checkVisibility();
            }, { threshold: 0, root: null });

            // Also watch for style changes (Alpine.js x-show uses display: none)
            const styleObserver = new MutationObserver(() => {
                checkVisibility();
            });

            styleObserver.observe(overlay, { attributes: true, attributeFilter: ['style'], subtree: false });
            observer.observe(overlay);

            // Store observers for cleanup
            window.modalObservers.set(modalId, {
                intersectionObserver: observer,
                mutationObserver: styleObserver
            });

            // Initial check
            setTimeout(() => {
                const isVisible = window.getComputedStyle(overlay).display !== 'none';
                if (isVisible) {
                    wasVisible = true;
                    window.handleModalOpen(overlay, modalId);
                }
            }, INITIAL_CHECK_DELAY_MS);
        };
    }
}
