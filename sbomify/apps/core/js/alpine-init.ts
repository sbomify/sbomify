import Alpine from 'alpinejs';
import morph from '@alpinejs/morph';
import mask from '@alpinejs/mask';
import persist from '@alpinejs/persist';
import focus from '@alpinejs/focus';
import intersect from '@alpinejs/intersect';
import collapse from '@alpinejs/collapse';
import anchor from '@alpinejs/anchor';
import { parseJsonScript } from './utils';
import { registerWebSocketStore } from './components/websocket-store';
import { showSuccess, showError, showWarning, showInfo, showToast, showConfirmation } from './alerts';
import { copyToClipboard, initCopyButtons } from './clipboard';

let initVulnerabilityChartFn: ((container: HTMLElement, chartType: string) => Promise<void>) | null = null;

let initializationPromise: Promise<void> | null = null;

declare global {
    interface Window {
        Alpine: typeof Alpine;
        parseJsonScript: typeof parseJsonScript;
    }
}

/**
 * Alpine.js Plugin Registry
 * 
 * Registers all Alpine.js plugins used throughout the application:
 * - morph: Enables DOM morphing for smooth transitions when updating elements
 * - mask: Provides input masking for formatted inputs (phone numbers, dates, etc.)
 * - persist: Automatically persists Alpine.js data to localStorage
 * - focus: Enhances focus management and trap focus within modals/dropdowns
 * - intersect: Triggers callbacks when elements enter/exit the viewport
 * - collapse: Provides smooth collapse/expand animations for elements
 * - anchor: Enables smooth scrolling to anchor links
 */
Alpine.plugin(morph);
Alpine.plugin(mask);

// Clean up corrupted localStorage entries before persist plugin initializes
// This prevents JSON parse errors from corrupted data
try {
    const keysToRemove: string[] = [];
    for (let i = 0; i < localStorage.length; i++) {
        const key = localStorage.key(i);
        if (key) {
            try {
                const value = localStorage.getItem(key);
                if (value !== null) {
                    // Try to parse as JSON to validate
                    JSON.parse(value);
                }
            } catch {
                // Invalid JSON - mark for removal
                console.warn(`[Persist] Found corrupted data in localStorage key "${key}". Will remove.`);
                keysToRemove.push(key);
            }
        }
    }
    // Remove corrupted entries
    keysToRemove.forEach(key => {
        try {
            localStorage.removeItem(key);
        } catch {
            // Ignore removal errors
        }
    });
} catch (e) {
    // localStorage might not be available (e.g., incognito mode)
    console.warn('[Persist] Could not clean localStorage:', e);
}

// Initialize persist plugin with error handling
// Note: We do NOT override Storage.prototype as that pollutes the global namespace
// and affects all other libraries. Instead, handle errors where they occur.
try {
    Alpine.plugin(persist);
} catch (e) {
    console.warn('[Persist] Failed to initialize persist plugin:', e);
}

Alpine.plugin(focus);
Alpine.plugin(intersect);
Alpine.plugin(collapse);
Alpine.plugin(anchor);

registerWebSocketStore();

Alpine.store('sidebar', {
    open: false,
    toggle(this: { open: boolean }) {
        this.open = !this.open;
    },
    close(this: { open: boolean }) {
        this.open = false;
    }
});

// Alerts store - provides global alert/notification methods
Alpine.store('alerts', {
    showSuccess(message: string) {
        return showSuccess(message);
    },
    showError(message: string) {
        return showError(message);
    },
    showWarning(message: string) {
        return showWarning(message);
    },
    showInfo(message: string) {
        return showInfo(message);
    },
    showToast(options: { title: string; message: string; type: 'success' | 'error' | 'warning' | 'info'; timer?: number; position?: 'top-end' | 'top' | 'top-start' | 'center' | 'bottom' | 'bottom-end' | 'bottom-start' }) {
        return showToast(options);
    },
    async showConfirmation(options: { title?: string; message: string; confirmButtonText?: string; cancelButtonText?: string; type?: 'success' | 'error' | 'warning' | 'info' }) {
        return await showConfirmation(options);
    }
});

// Clipboard store - provides clipboard operations
Alpine.store('clipboard', {
    async copy(text: string, successMessage?: string, errorMessage?: string) {
        return await copyToClipboard(text, successMessage, errorMessage);
    },
    initButtons(container: HTMLElement | Document = document) {
        initCopyButtons(container);
    }
});

// Modals store - provides modal focus trap and observer management
Alpine.store('modals', {
    triggerElements: {} as Record<string, HTMLElement>,
    observers: new Map<string, { intersectionObserver: IntersectionObserver; mutationObserver: MutationObserver }>(),

    getFocusableElements(this: { getFocusableElements: (container: HTMLElement) => HTMLElement[] }, container: HTMLElement): HTMLElement[] {
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
                const style = window.getComputedStyle(el);
                return style.display !== 'none' &&
                    style.visibility !== 'hidden' &&
                    !el.hasAttribute('disabled');
            });
    },

    handleTabKey(this: { getFocusableElements: (container: HTMLElement) => HTMLElement[] }, event: KeyboardEvent, modalElement: HTMLElement) {
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

        if (!modalContent.contains(currentElement)) {
            event.preventDefault();
            firstElement.focus();
            return;
        }

        if (event.shiftKey && currentElement === firstElement) {
            event.preventDefault();
            lastElement.focus();
        } else if (!event.shiftKey && currentElement === lastElement) {
            event.preventDefault();
            firstElement.focus();
        }
    },

    handleModalOpen(this: { getFocusableElements: (container: HTMLElement) => HTMLElement[]; triggerElements: Record<string, HTMLElement> }, modalElement: HTMLElement, modalId: string) {
        if (document.activeElement &&
            document.activeElement !== document.body &&
            !modalElement.contains(document.activeElement)) {
            this.triggerElements[modalId] = document.activeElement as HTMLElement;
        }

        const modalContent = modalElement.querySelector<HTMLElement>('.delete-modal');
        if (!modalContent) return;

        const focusableElements = this.getFocusableElements(modalContent);
        const FOCUS_DELAY_MS = 50;

        if (focusableElements.length > 0) {
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

            setTimeout(() => {
                elementToFocus?.focus();
            }, FOCUS_DELAY_MS);
        } else {
            modalContent.setAttribute('tabindex', '-1');
            setTimeout(() => {
                modalContent.focus();
            }, FOCUS_DELAY_MS);
        }
    },

    handleModalClose(this: { triggerElements: Record<string, HTMLElement> }, modalId: string) {
        const FOCUS_RETURN_DELAY_MS = 100;
        const triggerElement = this.triggerElements[modalId];
        if (triggerElement && triggerElement.focus) {
            setTimeout(() => {
                try {
                    triggerElement.focus();
                } catch (e) {
                    console.warn('Could not return focus to trigger element:', e);
                }
            }, FOCUS_RETURN_DELAY_MS);
        }
        delete this.triggerElements[modalId];
    },

    initModal(this: { observers: Map<string, { intersectionObserver: IntersectionObserver; mutationObserver: MutationObserver }>; handleModalOpen: (overlay: HTMLElement, modalId: string) => void; handleModalClose: (modalId: string) => void }, modalId: string, overlay: HTMLElement) {
        const INITIAL_CHECK_DELAY_MS = 150;
        const existingObservers = this.observers.get(modalId);
        if (existingObservers) {
            existingObservers.intersectionObserver.disconnect();
            existingObservers.mutationObserver.disconnect();
            this.observers.delete(modalId);
        }

        let wasVisible = false;
        let isProcessing = false;

        const checkVisibility = () => {
            if (isProcessing) return;
            isProcessing = true;

            const isVisible = window.getComputedStyle(overlay).display !== 'none';

            if (isVisible && !wasVisible) {
                wasVisible = true;
                this.handleModalOpen(overlay, modalId);
            } else if (!isVisible && wasVisible) {
                wasVisible = false;
                this.handleModalClose(modalId);
            }

            isProcessing = false;
        };

        const observer = new IntersectionObserver(() => {
            checkVisibility();
        }, { threshold: 0, root: null });

        const styleObserver = new MutationObserver(() => {
            checkVisibility();
        });

        styleObserver.observe(overlay, { attributes: true, attributeFilter: ['style'], subtree: false });
        observer.observe(overlay);

        this.observers.set(modalId, {
            intersectionObserver: observer,
            mutationObserver: styleObserver
        });

        setTimeout(() => {
            const isVisible = window.getComputedStyle(overlay).display !== 'none';
            if (isVisible) {
                wasVisible = true;
                this.handleModalOpen(overlay, modalId);
            }
        }, INITIAL_CHECK_DELAY_MS);
    }
});

// Charts store - provides chart initialization methods
Alpine.store('charts', {
    async initVulnerabilityChart(container: HTMLElement, chartType: string) {
        // Lazy load the function if not already loaded
        if (!initVulnerabilityChartFn) {
            try {
                const module = await import('../../vulnerability_scanning/js/vulnerability-chart-init');
                initVulnerabilityChartFn = module.initVulnerabilityChart;
            } catch (error) {
                console.error('Failed to load vulnerability chart init:', error);
                // Fallback to window function if available
                if (typeof window !== 'undefined' && window.initVulnerabilityChart) {
                    initVulnerabilityChartFn = window.initVulnerabilityChart;
                } else {
                    return;
                }
            }
        }
        if (initVulnerabilityChartFn) {
            await initVulnerabilityChartFn(container, chartType);
        }
    }
});

if (!window.Alpine) {
    window.Alpine = Alpine;
}
window.parseJsonScript = parseJsonScript;

export function initializeAlpine(): Promise<void> {
    if (initializationPromise) {
        return initializationPromise;
    }

    initializationPromise = Promise.resolve().then(() => {
        window.Alpine.start();
    });

    return initializationPromise;
}

export function isAlpineInitialized(): boolean {
    return initializationPromise !== null;
}

export default window.Alpine || Alpine;


