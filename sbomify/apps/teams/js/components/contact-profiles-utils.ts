import Alpine from 'alpinejs';
// Bootstrap JS removed - using Alpine.js instead

/**
 * Contact Profiles Utilities
 * Global functions and event handlers for contact profiles
 */

// Track event listeners for cleanup
const eventListeners: Array<{
    element: EventTarget;
    event: string;
    handler: EventListener;
    options?: boolean | AddEventListenerOptions;
}> = [];

declare global {
    interface Window {
        addContactRow?: (container: HTMLElement, entityPrefix: string) => void;
        showDeleteConfirmation?: (itemName: string, callback: () => void) => void;
        _alpineContactProfilesInitialized?: boolean;
    }
}

/**
 * Setup Contact Profiles Utilities
 * Initializes global event handlers and functions
 */
export function setupContactProfilesUtils(): void {
    // Use imported Alpine instead of window.Alpine
    // Initialize Alpine components when Alpine is ready
    function initAlpineComponents() {
        // Use imported Alpine or fallback to window.Alpine for backward compatibility
        const alpineInstance = Alpine || (typeof window !== 'undefined' && window.Alpine ? window.Alpine : null);
        if (!alpineInstance) {
            document.addEventListener('alpine:init', initAlpineComponents);
            return;
        }

        if (window._alpineContactProfilesInitialized) return;
        window._alpineContactProfilesInitialized = true;
    }

    initAlpineComponents();

    // Immediately initialize any component-metadata-formset or profile-form elements
    // This is necessary when this script is loaded via HTMX
    (function () {
        const alpineInstance = Alpine || (typeof window !== 'undefined' && window.Alpine ? window.Alpine : null);
        if (alpineInstance) {
            requestAnimationFrame(() => {
                const metadataFormset = document.querySelector('.component-metadata-formset') as HTMLElement;
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                if (metadataFormset && !(metadataFormset as any)._x_dataStack) {
                    alpineInstance.initTree(metadataFormset);
                }
                const profileForm = document.querySelector('.profile-form') as HTMLElement;
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                if (profileForm && !(profileForm as any)._x_dataStack) {
                    alpineInstance.initTree(profileForm);
                }
            });
        }
    })();

    // Global function to add contact row
    window.addContactRow = function (container: HTMLElement, entityPrefix: string) {
        if (!container) {
            console.warn('addContactRow: container element not found');
            return;
        }
        if (!entityPrefix) {
            console.warn('addContactRow: entityPrefix is required');
            return;
        }
        const contactPrefix = `${entityPrefix}-contacts`;
        const entityCard = container.closest('.entity-card') as HTMLElement;
        if (!entityCard) {
            console.warn('addContactRow: entity-card element not found');
            return;
        }

        let totalInput = container.querySelector(`input[name="${contactPrefix}-TOTAL_FORMS"]`) as HTMLInputElement;
        if (!totalInput) {
            totalInput = entityCard.querySelector(`input[name="${contactPrefix}-TOTAL_FORMS"]`) as HTMLInputElement;
        }

        if (!totalInput) {
            const mgmtDiv = document.createElement('div');
            mgmtDiv.innerHTML = `
                <input type="hidden" name="${contactPrefix}-TOTAL_FORMS" value="0" id="id_${contactPrefix}-TOTAL_FORMS">
                <input type="hidden" name="${contactPrefix}-INITIAL_FORMS" value="0" id="id_${contactPrefix}-INITIAL_FORMS">
                <input type="hidden" name="${contactPrefix}-MIN_NUM_FORMS" value="0" id="id_${contactPrefix}-MIN_NUM_FORMS">
                <input type="hidden" name="${contactPrefix}-MAX_NUM_FORMS" value="1000" id="id_${contactPrefix}-MAX_NUM_FORMS">
            `;
            container.insertBefore(mgmtDiv, container.firstChild);
            totalInput = container.querySelector(`input[name="${contactPrefix}-TOTAL_FORMS"]`) as HTMLInputElement;
        }

        if (!totalInput) {
            console.error('addContactRow: failed to create/find TOTAL_FORMS input');
            return;
        }

        if (typeof totalInput.value === 'undefined') {
            console.error('addContactRow: TOTAL_FORMS input has no value to parse');
            return;
        }
        const index = parseInt(totalInput.value);
        const newPrefix = `${contactPrefix}-${index}`;

        let newRow: HTMLElement | null = null;
        const existingContact = container.querySelector('.contact-card') as HTMLElement;

        if (existingContact) {
            newRow = existingContact.cloneNode(true) as HTMLElement;
            newRow.querySelectorAll('input, select, textarea').forEach(input => {
                const htmlInput = input as HTMLInputElement;
                if (htmlInput.name) {
                    const nameMatch = htmlInput.name.match(/^(.+?)-(name|email|phone|DELETE|id|is_author|is_security_contact|is_technical_contact)$/);
                    if (nameMatch) {
                        htmlInput.name = `${newPrefix}-${nameMatch[2]}`;
                        htmlInput.id = `id_${htmlInput.name}`;

                        if (nameMatch[2] === 'id') {
                            htmlInput.value = '';
                        }
                        if (['is_author', 'is_security_contact', 'is_technical_contact'].includes(nameMatch[2])) {
                            htmlInput.checked = false;
                        }
                    }
                }
            });
            newRow.querySelectorAll('input[type="text"], input[type="email"]').forEach(input => {
                const htmlInput = input as HTMLInputElement;
                if (htmlInput.name && !htmlInput.name.includes('DELETE') && !htmlInput.name.includes('id')) {
                    htmlInput.value = '';
                }
            });
            const deleteInput = newRow.querySelector(`input[name="${newPrefix}-DELETE"]`) as HTMLInputElement;
            if (deleteInput) {
                deleteInput.value = '';
            }
        } else {
            newRow = document.createElement('div');
            newRow.className = 'contact-card border-bottom';
            newRow.setAttribute('x-data', 'contactEntry');
            newRow.setAttribute('x-show', '!deleted');
            newRow.innerHTML = `
                <input type="hidden" name="${newPrefix}-id" id="id_${newPrefix}-id">
                <input type="hidden" name="${newPrefix}-DELETE" x-model="deleted" value="">
                <div class="d-flex align-items-center py-2 px-3 gap-3">
                    <div class="flex-shrink-0">
                        <div class="contact-avatar-circle">
                            <i class="fas fa-user-pen contact-icon-purple"></i>
                        </div>
                    </div>
                    <div class="flex-shrink-0 contact-field-name">
                        <input type="text" name="${newPrefix}-name" id="id_${newPrefix}-name" class="form-control form-control-sm bg-white rounded-2" placeholder="Name *" :required="!deleted && editing" title="Click to edit name" aria-label="Contact Name">
                    </div>
                    <div class="flex-grow-1 contact-field-email">
                        <input type="email" name="${newPrefix}-email" id="id_${newPrefix}-email" class="form-control form-control-sm bg-white rounded-2" placeholder="Email *" :required="!deleted && editing" title="Please enter a valid email address (e.g., contact@example.com)" aria-label="Contact Email">
                    </div>
                    <div class="flex-shrink-0 contact-field-phone">
                        <input type="text" name="${newPrefix}-phone" id="id_${newPrefix}-phone" class="form-control form-control-sm bg-white rounded-2" placeholder="Phone" title="Click to edit phone" aria-label="Contact Phone">
                    </div>
                    <div class="flex-shrink-0">
                        <button type="button" class="btn btn-sm btn-link p-1" @click="removeContact" title="Remove contact" aria-label="Remove contact">
                            <i class="fas fa-trash-alt text-danger"></i>
                        </button>
                    </div>
                </div>
            `;
            const alpineInstance = Alpine || (typeof window !== 'undefined' ? window.Alpine : null);
            if (alpineInstance) {
                alpineInstance.initTree(newRow);
            }
        }

        container.appendChild(newRow);
        totalInput.value = (index + 1).toString();
    };

    // Tooltip initialization - Alpine tooltips auto-initialize from data-bs-toggle="tooltip" or title attributes
    function initTooltips() {
        // Alpine tooltips are handled by the tooltip directive and HTMX lifecycle
        // No manual initialization needed
    }

    // HTMX event listeners
    const beforeSwapHandler = function (event: Event) {
        const customEvent = event as CustomEvent;
        const targetId = (customEvent.detail?.target as HTMLElement)?.id;
        if (targetId === 'contact-profiles-content' || targetId === 'custom-contact-form-container') {
            const container = customEvent.detail.target as HTMLElement;

            // Alpine tooltips are cleaned up automatically by HTMX lifecycle
            // No manual cleanup needed

            // Remove orphaned tooltip elements
            document.querySelectorAll('.tooltip.show').forEach((tooltipEl) => {
                const id = tooltipEl.getAttribute('id');
                if (id) {
                    const trigger = container.querySelector(`[aria-describedby="${id}"]`);
                    if (trigger) tooltipEl.remove();
                }
            });
        }
    };
    document.body.addEventListener('htmx:beforeSwap', beforeSwapHandler);
    eventListeners.push({
        element: document.body,
        event: 'htmx:beforeSwap',
        handler: beforeSwapHandler
    });

    const afterSettleHandler = function (event: Event) {
        const customEvent = event as CustomEvent;
        const targetId = (customEvent.detail?.target as HTMLElement)?.id;
        if (targetId === 'contact-profiles-content' || targetId === 'custom-contact-form-container') {
            initAlpineComponents();
            requestAnimationFrame(() => {
                const alpineInstance = Alpine || (typeof window !== 'undefined' ? window.Alpine : null);
                if (alpineInstance) {
                    alpineInstance.initTree(customEvent.detail.target as HTMLElement);
                }
                initTooltips();
            });
        }
    };
    document.body.addEventListener('htmx:afterSettle', afterSettleHandler);
    eventListeners.push({
        element: document.body,
        event: 'htmx:afterSettle',
        handler: afterSettleHandler
    });

    // Initialize tooltips on page load
    const domContentLoadedHandler = () => initTooltips();
    document.addEventListener('DOMContentLoaded', domContentLoadedHandler);
    eventListeners.push({
        element: document,
        event: 'DOMContentLoaded',
        handler: domContentLoadedHandler
    });

    // Delete confirmation modal functionality
    (function () {
        let deleteCallback: (() => void) | null = null;

        function getModal(): HTMLElement | null {
            return document.getElementById('delete-confirmation-modal');
        }

        window.showDeleteConfirmation = function (itemName: string, callback: () => void) {
            const modal = getModal();
            if (!modal) return;

            const itemNameEl = document.getElementById('delete-item-name');
            if (itemNameEl) {
                itemNameEl.textContent = itemName;
            }
            deleteCallback = callback;

            // Use Alpine state to open modal
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            const modalData = Alpine.$data(modal) as any;
            if (modalData && typeof modalData.modalOpen === 'boolean') {
                modalData.modalOpen = true;
            } else if (modalData && typeof modalData.open === 'boolean') {
                modalData.open = true;
            }
        };

        document.addEventListener('click', function (e) {
            const target = e.target as HTMLElement;
            if (target && target.id === 'confirm-delete-btn') {
                if (deleteCallback) {
                    deleteCallback();
                    deleteCallback = null;
                }
                const modal = getModal();
                if (modal) {
                    // Use Alpine state to close modal
                    // eslint-disable-next-line @typescript-eslint/no-explicit-any
                    const modalData = Alpine.$data(modal) as any;
                    if (modalData && typeof modalData.modalOpen === 'boolean') {
                        modalData.modalOpen = false;
                    } else if (modalData && typeof modalData.open === 'boolean') {
                        modalData.open = false;
                    } else if (modalData && typeof modalData.close === 'function') {
                        modalData.close();
                    }
                }
            }
        });

        document.addEventListener('hidden.bs.modal', function (e) {
            const target = e.target as HTMLElement;
            if (target && target.id === 'delete-confirmation-modal') {
                deleteCallback = null;
            }
        });
    })();
}

/**
 * Destroy Contact Profiles Utilities
 * Removes all event listeners and cleans up resources
 */
export function destroyContactProfilesUtils(): void {
    // Remove all tracked event listeners
    eventListeners.forEach(({ element, event, handler, options }) => {
        if (options !== undefined) {
            element.removeEventListener(event, handler, options);
        } else {
            element.removeEventListener(event, handler);
        }
    });

    // Clear the listeners array
    eventListeners.length = 0;

    // Reset initialization flag
    window._alpineContactProfilesInitialized = false;

    // Remove global function
    delete window.addContactRow;
    delete window.showDeleteConfirmation;
}
