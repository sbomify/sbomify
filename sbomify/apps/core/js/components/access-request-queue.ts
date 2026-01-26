import Alpine from 'alpinejs';
// Bootstrap JS removed - using Alpine.js instead

// Type for alerts store
interface AlertsStore {
    showConfirmation: (options: {
        title?: string;
        message: string;
        confirmButtonText?: string;
        cancelButtonText?: string;
        type?: 'success' | 'error' | 'warning' | 'info';
    }) => Promise<boolean>;
}

// Type for component with $store
interface AccessRequestQueueComponent {
    $store?: {
        alerts?: AlertsStore;
    };
    $el: HTMLElement;
}

/**
 * Access Request Queue Component
 * Handles access request management, modals, and form submissions
 */
export function registerAccessRequestQueue(): void {
    Alpine.data('accessRequestQueue', function (this: AccessRequestQueueComponent) {
        return {
            htmxHandler: null as ((event: CustomEvent) => void) | null,
            refreshHandler: null as (() => void) | null,
            closeModalHandler: null as (() => void) | null,

            init() {
                // Initialize reject buttons
                this.initRejectButtons();

                // Initialize tooltips
                this.initTooltips();

                // Set up modal handlers
                this.setupModals();

                // Listen for HTMX swaps
                this.htmxHandler = (event: CustomEvent) => {
                    const target = event.detail?.target as HTMLElement;
                    if (target && (target.id?.includes('access-request') || target.querySelector('.reject-btn'))) {
                        this.initRejectButtons();
                        this.initTooltips();
                    }
                };
                document.body.addEventListener('htmx:afterSwap', this.htmxHandler as EventListener);

                // Listen for custom events
                this.refreshHandler = () => {
                    setTimeout(() => {
                        this.initRejectButtons();
                        this.initTooltips();
                    }, 100);
                };
                document.body.addEventListener('refreshAccessRequests', this.refreshHandler);

                this.closeModalHandler = () => {
                    this.closeInviteModal();
                };
                document.body.addEventListener('closeInviteModal', this.closeModalHandler);
            },

            destroy() {
                // Remove event listeners
                if (this.htmxHandler) {
                    document.body.removeEventListener('htmx:afterSwap', this.htmxHandler as EventListener);
                    this.htmxHandler = null;
                }
                if (this.refreshHandler) {
                    document.body.removeEventListener('refreshAccessRequests', this.refreshHandler);
                    this.refreshHandler = null;
                }
                if (this.closeModalHandler) {
                    document.body.removeEventListener('closeInviteModal', this.closeModalHandler);
                    this.closeModalHandler = null;
                }
            },

            async initRejectButtons() {
                // Wait for showConfirmation to be available
                let retries = 0;
                const maxRetries = 100;

                const tryInit = () => {
                    // Check if alerts store is available
                    try {
                        const alertsStore = (this as unknown as AccessRequestQueueComponent).$store?.alerts;
                        if (alertsStore && typeof alertsStore.showConfirmation === 'function') {
                            this.attachRejectHandlers();
                        } else if (retries < maxRetries) {
                            retries++;
                            setTimeout(tryInit, 50);
                        } else {
                            console.warn('Alerts store not available, using fallback');
                            this.attachRejectHandlersFallback();
                        }
                    } catch {
                        if (retries < maxRetries) {
                            retries++;
                            setTimeout(tryInit, 50);
                        } else {
                            console.warn('Alerts store not available, using fallback');
                            this.attachRejectHandlersFallback();
                        }
                    }
                };

                tryInit();
            },

            attachRejectHandlers() {
                // Query within component scope
                const rejectButtons = this.$el.querySelectorAll('.reject-btn');
                rejectButtons.forEach((button: Element) => {
                    const htmlButton = button as HTMLElement;
                    // Remove existing listeners by cloning
                    const newButton = htmlButton.cloneNode(true) as HTMLElement;
                    htmlButton.parentNode?.replaceChild(newButton, htmlButton);

                    newButton.addEventListener('click', async (e) => {
                        e.preventDefault();
                        await this.handleRejectClick(newButton);
                    });
                });
            },

            attachRejectHandlersFallback() {
                const rejectButtons = this.$el.querySelectorAll('.reject-btn');
                rejectButtons.forEach((button: Element) => {
                    const htmlButton = button as HTMLElement;
                    htmlButton.addEventListener('click', (e) => {
                        e.preventDefault();
                        this.handleRejectClickFallback(htmlButton);
                    });
                });
            },

            async handleRejectClick(button: HTMLElement) {
                const requestId = button.getAttribute('data-request-id');
                const userEmail = button.getAttribute('data-user-email');
                const form = document.getElementById(`access-request-form-${requestId}`) as HTMLFormElement;

                if (!form) {
                    console.error('Form not found for request ID:', requestId);
                    return;
                }

                try {
                    const alertsStore = (this as unknown as AccessRequestQueueComponent).$store?.alerts;
                    if (!alertsStore || !alertsStore.showConfirmation) {
                        throw new Error('Alerts store not available');
                    }

                    const confirmed = await alertsStore.showConfirmation({
                        title: 'Reject Access Request?',
                        message: `Are you sure you want to reject the access request from ${userEmail}? This action cannot be undone.`,
                        confirmButtonText: 'Reject',
                        cancelButtonText: 'Cancel',
                        type: 'warning'
                    });

                    if (confirmed) {
                        this.submitRejectForm(form);
                    }
                } catch (error) {
                    console.error('Error showing confirmation:', error);
                    if (confirm(`Are you sure you want to reject the access request from ${userEmail}?`)) {
                        this.submitRejectForm(form);
                    }
                }
            },

            handleRejectClickFallback(button: HTMLElement) {
                const requestId = button.getAttribute('data-request-id');
                const userEmail = button.getAttribute('data-user-email');
                const form = document.getElementById(`access-request-form-${requestId}`) as HTMLFormElement;

                if (!form) {
                    console.error('Form not found for request ID:', requestId);
                    return;
                }

                if (confirm(`Are you sure you want to reject the access request from ${userEmail}?`)) {
                    this.submitRejectForm(form);
                }
            },

            submitRejectForm(form: HTMLFormElement) {
                // Remove any existing action input
                form.querySelectorAll('input[name="action"]').forEach((input) => {
                    if ((input as HTMLInputElement).type === 'hidden') {
                        input.remove();
                    }
                });

                // Create hidden input for action
                const actionInput = document.createElement('input');
                actionInput.type = 'hidden';
                actionInput.name = 'action';
                actionInput.value = 'reject';
                form.appendChild(actionInput);

                // Submit the form
                form.submit();
            },

            initTooltips() {
                if (!window.bootstrap || typeof (window.bootstrap as { Tooltip?: unknown }).Tooltip === 'undefined') return;

                // Alpine tooltips are auto-initialized from x-tooltip or title attributes
                // No manual initialization needed - tooltips will be handled by Alpine directive
            },

            setupModals() {
                // Cancel Invitation Modal - use Alpine approach
                this.setupCancelModal();

                // Revoke Access Modal  
                this.setupRevokeModal();

                // Access Request Info Modal
                this.setupInfoModal();
            },

            /**
             * Setup cancel invitation modal with Alpine event handling
             */
            setupCancelModal() {
                const cancelModal = document.getElementById('cancelInvitationModal');
                if (!cancelModal) return;

                // Listen for Alpine modal open event instead of Bootstrap
                cancelModal.addEventListener('open-modal', ((event: CustomEvent) => {
                    const button = event.detail?.button as HTMLElement;
                    if (!button) return;

                    const invitationId = button.getAttribute('data-invitation-id');
                    const invitationEmail = button.getAttribute('data-invitation-email');

                    const idInput = document.getElementById('cancelInvitationModalInvitationId') as HTMLInputElement;
                    if (idInput) idInput.value = invitationId || '';

                    const emailElement = document.getElementById('cancelInvitationModalDisplayEmail');
                    if (emailElement && invitationEmail) {
                        emailElement.textContent = invitationEmail;
                    }
                }) as EventListener);
            },

            /**
             * Setup revoke access modal with Alpine event handling
             */
            setupRevokeModal() {
                const revokeModal = document.getElementById('revokeAccessModal');
                if (!revokeModal) return;

                revokeModal.addEventListener('open-modal', ((event: CustomEvent) => {
                    const button = event.detail?.button as HTMLElement;
                    if (!button) return;

                    const requestId = button.getAttribute('data-request-id');
                    const userEmail = button.getAttribute('data-user-email');

                    const idInput = document.getElementById('revokeAccessModalRequestId') as HTMLInputElement;
                    if (idInput) idInput.value = requestId || '';

                    const nameElement = document.getElementById('revokeAccessModalDisplayName');
                    if (nameElement && userEmail) {
                        nameElement.textContent = userEmail;
                    }
                }) as EventListener);
            },

            /**
             * Setup info modal with Alpine event handling
             */
            setupInfoModal() {
                const infoModal = document.getElementById('accessRequestInfoModal');
                if (!infoModal) return;

                infoModal.addEventListener('open-modal', ((event: CustomEvent) => {
                    const button = event.detail?.button as HTMLElement;
                    if (button) {
                        this.populateInfoModal(button);
                    }
                }) as EventListener);
            },

            populateInfoModal(button: HTMLElement) {
                // Get all data attributes
                const data = {
                    userName: button.getAttribute('data-user-name') || '—',
                    userEmail: button.getAttribute('data-user-email') || '—',
                    status: button.getAttribute('data-status') || '—',
                    requestedAt: button.getAttribute('data-requested-at') || '—',
                    decidedAt: button.getAttribute('data-decided-at') || '',
                    decidedBy: button.getAttribute('data-decided-by') || '',
                    revokedAt: button.getAttribute('data-revoked-at') || '',
                    revokedBy: button.getAttribute('data-revoked-by') || '',
                    notes: button.getAttribute('data-notes') || '',
                    ndaSigned: button.getAttribute('data-nda-signed') === 'true',
                    ndaSignedName: button.getAttribute('data-nda-signed-name') || '',
                    ndaSignedAt: button.getAttribute('data-nda-signed-at') || '',
                    ndaIp: button.getAttribute('data-nda-ip') || '',
                    ndaModified: button.getAttribute('data-nda-modified') === 'true',
                    ndaCurrent: button.getAttribute('data-nda-current') === 'true',
                    ndaUrl: button.getAttribute('data-nda-url') || ''
                };

                // Populate user info
                const userNameEl = document.getElementById('info-user-name');
                const userEmailEl = document.getElementById('info-user-email');
                if (userNameEl) userNameEl.textContent = data.userName;
                if (userEmailEl) userEmailEl.textContent = data.userEmail;

                // Populate status with badge
                const statusEl = document.getElementById('info-status');
                if (statusEl) {
                    const badges: Record<string, string> = {
                        'pending': '<span class="badge bg-warning">Pending</span>',
                        'approved': '<span class="badge bg-success">Approved</span>',
                        'rejected': '<span class="badge bg-danger">Rejected</span>',
                        'revoked': '<span class="badge bg-secondary">Revoked</span>'
                    };
                    statusEl.innerHTML = badges[data.status] || data.status;
                }

                // Populate dates
                const requestedAtEl = document.getElementById('info-requested-at');
                if (requestedAtEl) requestedAtEl.textContent = data.requestedAt;

                // Show/hide decided section
                const decidedSection = document.getElementById('info-decided-section');
                const decidedBySection = document.getElementById('info-decided-by-section');
                if (data.decidedAt) {
                    const decidedAtEl = document.getElementById('info-decided-at');
                    if (decidedAtEl) decidedAtEl.textContent = data.decidedAt;
                    if (decidedSection) decidedSection.style.display = 'block';
                } else if (decidedSection) {
                    decidedSection.style.display = 'none';
                }
                if (data.decidedBy) {
                    const decidedByEl = document.getElementById('info-decided-by');
                    if (decidedByEl) decidedByEl.textContent = data.decidedBy;
                    if (decidedBySection) decidedBySection.style.display = 'block';
                } else if (decidedBySection) {
                    decidedBySection.style.display = 'none';
                }

                // Show/hide revoked section
                const revokedSection = document.getElementById('info-revoked-section');
                const revokedBySection = document.getElementById('info-revoked-by-section');
                if (data.revokedAt) {
                    const revokedAtEl = document.getElementById('info-revoked-at');
                    if (revokedAtEl) revokedAtEl.textContent = data.revokedAt;
                    if (revokedSection) revokedSection.style.display = 'block';
                } else if (revokedSection) {
                    revokedSection.style.display = 'none';
                }
                if (data.revokedBy) {
                    const revokedByEl = document.getElementById('info-revoked-by');
                    if (revokedByEl) revokedByEl.textContent = data.revokedBy;
                    if (revokedBySection) revokedBySection.style.display = 'block';
                } else if (revokedBySection) {
                    revokedBySection.style.display = 'none';
                }

                // Show/hide NDA section
                const ndaSection = document.getElementById('info-nda-section');
                if (data.ndaSigned) {
                    const signedNameEl = document.getElementById('info-nda-signed-name');
                    const signedAtEl = document.getElementById('info-nda-signed-at');
                    const ipEl = document.getElementById('info-nda-ip');
                    const modifiedEl = document.getElementById('info-nda-modified');
                    const urlEl = document.getElementById('info-nda-url');

                    if (signedNameEl) signedNameEl.textContent = data.ndaSignedName || '—';
                    if (signedAtEl) signedAtEl.textContent = data.ndaSignedAt || '—';
                    if (ipEl) ipEl.textContent = data.ndaIp || '—';

                    if (modifiedEl) {
                        if (data.ndaCurrent) {
                            if (data.ndaModified) {
                                modifiedEl.innerHTML = '<span class="badge bg-danger" title="NDA document has been modified after signing">Modified</span>';
                            } else {
                                modifiedEl.innerHTML = '<span class="badge bg-success">Valid</span>';
                            }
                        } else {
                            modifiedEl.innerHTML = '<span class="badge bg-warning" title="NDA version has been updated. User needs to sign the new version.">Invalid</span>';
                        }
                    }

                    if (urlEl) {
                        if (data.ndaUrl) {
                            urlEl.innerHTML = `<a href="${data.ndaUrl}" target="_blank" class="text-decoration-none"><i class="fas fa-external-link-alt me-1"></i>View NDA Document</a>`;
                        } else {
                            urlEl.textContent = '—';
                        }
                    }

                    if (ndaSection) ndaSection.style.display = 'block';
                } else if (ndaSection) {
                    ndaSection.style.display = 'none';
                }

                // Show/hide notes section
                const notesSection = document.getElementById('info-notes-section');
                if (data.notes) {
                    const notesEl = document.getElementById('info-notes');
                    if (notesEl) notesEl.textContent = data.notes;
                    if (notesSection) notesSection.style.display = 'block';
                } else if (notesSection) {
                    notesSection.style.display = 'none';
                }
            },

            closeInviteModal() {
                const modalElement = document.getElementById('inviteUserModal');
                if (!modalElement) return;

                // Close modal using Alpine state
                try {
                    // Type assertion for Alpine component data
                    interface ModalData {
                        modalOpen?: boolean;
                        open?: boolean;
                        close?: () => void;
                    }
                    const modalData = Alpine.$data(modalElement) as ModalData | null;
                    if (modalData) {
                        if (typeof modalData.modalOpen === 'boolean') {
                            modalData.modalOpen = false;
                        } else if (typeof modalData.open === 'boolean') {
                            modalData.open = false;
                        } else if (typeof modalData.close === 'function') {
                            modalData.close();
                        }
                    }
                } catch {
                    // Modal might not have Alpine data
                }

                // Reset form
                const form = modalElement.querySelector('form');
                if (form) {
                    form.reset();
                }
            }
        };
    });
}
