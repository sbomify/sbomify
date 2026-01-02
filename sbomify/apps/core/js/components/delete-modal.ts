import { showSuccess, showError } from '../alerts';

interface DeleteModalConfig {
    modalId: string;
    hxUrl: string;
    hxMethod?: string;
    successMessage: string;
    csrfToken: string;
    redirectUrl?: string;
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

declare global {
    interface Window {
        getDeleteModalData: (config: DeleteModalConfig) => DeleteModalData;
        modalFocusTrap: ModalFocusTrap;
        handleTabKey: (event: KeyboardEvent) => void;
        handleModalOpen: (modalElement: HTMLElement, modalId: string) => void;
        handleModalClose: (modalId: string) => void;
        initDeleteModal: (modalId: string, overlay: HTMLElement) => void;
    }
}

export function registerDeleteModal() {
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
                    }, 50);
                } else {
                    // If no focusable elements, focus the modal content itself
                    modalContent.setAttribute('tabindex', '-1');
                    setTimeout(() => {
                        modalContent.focus();
                    }, 50);
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
                    }, 100);
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
                        this[config.modalId] = false;
                        const errorMsg = 'Security error: Missing CSRF token. Please reload the page and try again.';
                        console.error(errorMsg);
                        showError(errorMsg); // Use imported function
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

                        this[config.modalId] = false;

                        if (response.ok) {
                            showSuccess(config.successMessage); // Use imported function
                            if (config.redirectUrl) {
                                window.location.href = config.redirectUrl;
                            }
                        } else {
                            console.error('Delete failed:', response.status);
                            showError('Failed to delete. Please try again.'); // Use imported function
                        }
                    } catch (error) {
                        this[config.modalId] = false;
                        console.error('Delete error:', error);
                        showError('An error occurred. Please try again.'); // Use imported function
                    } finally {
                        this.isLoading = false;
                    }
                }
            };
        };
    }

    if (!window.initDeleteModal) {
        window.initDeleteModal = function (modalId: string, overlay: HTMLElement) {
            let wasVisible = false;

            // Watch for visibility changes using IntersectionObserver
            const observer = new IntersectionObserver((entries) => {
                const isVisible = entries[0].isIntersecting || window.getComputedStyle(overlay).display !== 'none';

                if (isVisible && !wasVisible) {
                    // Modal just opened
                    wasVisible = true;
                    window.handleModalOpen(overlay, modalId);
                } else if (!isVisible && wasVisible) {
                    // Modal just closed
                    wasVisible = false;
                    window.handleModalClose(modalId);
                }
            }, { threshold: 0, root: null });

            // Also watch for style changes (Alpine.js x-show uses display: none)
            const styleObserver = new MutationObserver(() => {
                const isVisible = window.getComputedStyle(overlay).display !== 'none';

                if (isVisible && !wasVisible) {
                    wasVisible = true;
                    window.handleModalOpen(overlay, modalId);
                } else if (!isVisible && wasVisible) {
                    wasVisible = false;
                    window.handleModalClose(modalId);
                }
            });

            styleObserver.observe(overlay, { attributes: true, attributeFilter: ['style'], subtree: false });
            observer.observe(overlay);

            // Initial check
            setTimeout(() => {
                const isVisible = window.getComputedStyle(overlay).display !== 'none';
                if (isVisible) {
                    wasVisible = true;
                    window.handleModalOpen(overlay, modalId);
                }
            }, 150);
        };
    }
}
