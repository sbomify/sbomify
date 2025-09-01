/**
 * Advanced formset management for component metadata editing
 * Handles dynamic add/remove of contacts, authors, and licenses with proper UX
 */

interface FormsetConfig {
    containerSelector: string;
    formClass: string;
    totalFormsSelector: string;
    prefix: string;
    emptyFormTemplate?: string;
}

interface LicenseData {
    key: string;
    name: string;
    origin: string;
    url?: string;
}

declare global {
    interface Window {
        licenseData: LicenseData[];
    }
}

declare const licenseData: LicenseData[];

class MetadataFormsetManager {
    private formsetConfigs: Record<string, FormsetConfig> = {
        'supplier_contacts': {
            containerSelector: '#supplier-contacts-formset',
            formClass: 'supplier-contact-form',
            totalFormsSelector: 'input[name="supplier_contacts-TOTAL_FORMS"]',
            prefix: 'supplier_contacts'
        },
        'authors': {
            containerSelector: '#authors-formset',
            formClass: 'author-form',
            totalFormsSelector: 'input[name="authors-TOTAL_FORMS"]',
            prefix: 'authors'
        },
        'licenses': {
            containerSelector: '#licenses-formset',
            formClass: 'license-form',
            totalFormsSelector: 'input[name="licenses-TOTAL_FORMS"]',
            prefix: 'licenses'
        }
    };

    private licenseAutocompleteInstances: Set<HTMLInputElement> = new Set();

    constructor() {
        this.init();
        this.setupFormSubmissionHandling();
    }

    private init(): void {
        this.initializeAddButtons();
        this.initializeRemoveButtons();
        this.initializeLicenseAutocomplete();
        this.initializeLicenseTypeHandlers();
        this.initializeSupplierUrls();
        this.initializeRealTimeValidationForExistingForms();
        this.initializeFormProgress();
    }

    private initializeAddButtons(): void {
        // Add Contact button
        const addContactBtn = document.querySelector('.add-contact-btn') as HTMLButtonElement;
        if (addContactBtn) {
            addContactBtn.addEventListener('click', () => this.addForm('supplier_contacts'));
        }

        // Add Author button
        const addAuthorBtn = document.querySelector('.add-author-btn') as HTMLButtonElement;
        if (addAuthorBtn) {
            addAuthorBtn.addEventListener('click', () => this.addForm('authors'));
        }

        // Add License button
        const addLicenseBtn = document.querySelector('.add-license-btn') as HTMLButtonElement;
        if (addLicenseBtn) {
            addLicenseBtn.addEventListener('click', () => this.addForm('licenses'));
        }
    }

    private initializeRemoveButtons(): void {
        document.addEventListener('click', (e) => {
            const target = e.target as HTMLElement;
            const removeBtn = target.closest('.remove-item-btn') as HTMLButtonElement;

            if (removeBtn) {
                e.preventDefault();
                this.showRemoveConfirmation(removeBtn);
            }
        });
    }

    private showRemoveConfirmation(button: HTMLButtonElement): void {
        const formContainer = button.closest(`.${this.getFormClassFromButton(button)}`) as HTMLElement;
        const itemType = this.getItemTypeFromButton(button);
        const itemName = this.getItemNameFromForm(formContainer, itemType);

        // Create and show confirmation modal
        const modal = this.createConfirmationModal(itemType, itemName, () => {
            this.removeForm(formContainer, button);
        });

        document.body.appendChild(modal);
        const bootstrapModal = new (window as any).bootstrap.Modal(modal);
        bootstrapModal.show();

        // Remove modal from DOM when hidden
        modal.addEventListener('hidden.bs.modal', () => {
            document.body.removeChild(modal);
        });
    }

    private createConfirmationModal(itemType: string, itemName: string, onConfirm: () => void): HTMLElement {
        const modal = document.createElement('div');
        modal.className = 'modal fade';
        modal.setAttribute('tabindex', '-1');
        modal.innerHTML = `
            <div class="modal-dialog">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">Remove ${itemType}</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <p>Are you sure you want to remove this ${itemType}?</p>
                        ${itemName ? `<p class="text-muted"><strong>${itemName}</strong></p>` : ''}
                        <p class="text-warning"><i class="fas fa-exclamation-triangle me-2"></i>This action cannot be undone.</p>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
                        <button type="button" class="btn btn-danger confirm-remove-btn">
                            <i class="fas fa-trash me-2"></i>Remove ${itemType}
                        </button>
                    </div>
                </div>
            </div>
        `;

        const confirmBtn = modal.querySelector('.confirm-remove-btn') as HTMLButtonElement;
        confirmBtn.addEventListener('click', () => {
            onConfirm();
            const bootstrapModal = (window as any).bootstrap.Modal.getInstance(modal);
            bootstrapModal.hide();
        });

        return modal;
    }

    private getFormClassFromButton(button: HTMLButtonElement): string {
        if (button.classList.contains('remove-contact-btn')) return 'supplier-contact-form';
        if (button.classList.contains('remove-author-btn')) return 'author-form';
        if (button.classList.contains('remove-license-btn')) return 'license-form';
        return '';
    }

    private getItemTypeFromButton(button: HTMLButtonElement): string {
        if (button.classList.contains('remove-contact-btn')) return 'Contact';
        if (button.classList.contains('remove-author-btn')) return 'Author';
        if (button.classList.contains('remove-license-btn')) return 'License';
        return 'Item';
    }

    private getItemNameFromForm(form: HTMLElement, itemType: string): string {
        if (itemType === 'Contact' || itemType === 'Author') {
            const nameInput = form.querySelector('input[name*="name"]') as HTMLInputElement;
            return nameInput?.value || 'Unnamed';
        } else if (itemType === 'License') {
            const licenseIdInput = form.querySelector('input[name*="license_id"]') as HTMLInputElement;
            return licenseIdInput?.value || 'Unnamed license';
        }
        return '';
    }

    private removeForm(formContainer: HTMLElement, button: HTMLButtonElement): void {
        const deleteField = formContainer.querySelector('input[name*="DELETE"]') as HTMLInputElement;

        if (deleteField) {
            // Mark for deletion
            deleteField.checked = true;
            formContainer.style.display = 'none';
        } else {
            // Remove completely if it's a new form
            formContainer.remove();
            this.updateFormCounts();
        }

        // Show success message
        const itemType = this.getItemTypeFromButton(button);
        this.showSuccessMessage(`${itemType} removed successfully`);
    }

    private addForm(formsetType: string): void {
        const config = this.formsetConfigs[formsetType];
        const container = document.querySelector(config.containerSelector) as HTMLElement;
        const totalFormsInput = document.querySelector(config.totalFormsSelector) as HTMLInputElement;

        if (!container || !totalFormsInput) {
            console.error(`Formset elements not found for ${formsetType}`);
            return;
        }

        const currentFormCount = parseInt(totalFormsInput.value);
        const newFormIndex = currentFormCount;

        // Try to clone existing form, or create from template
        let newForm = this.cloneExistingForm(container, config, newFormIndex);

        if (!newForm) {
            newForm = this.createFormFromTemplate(formsetType, newFormIndex);
        }

        if (newForm) {
            container.appendChild(newForm);
            totalFormsInput.value = (currentFormCount + 1).toString();

            // Initialize license functionality for new license forms
            if (formsetType === 'licenses') {
                this.initializeLicenseFormHandlers(newForm);
            }

            // Set up real-time validation for the new form
            this.setupRealTimeValidation(newForm);

            // Add visual feedback for successful addition
            newForm.classList.add('form-added');
            setTimeout(() => {
                newForm.classList.remove('form-added');
            }, 600);

            // Show success message
            const itemType = formsetType === 'supplier_contacts' ? 'Contact' :
                           formsetType === 'authors' ? 'Author' : 'License';
            this.showSuccessMessage(`${itemType} added successfully`);

            // Scroll to new form and focus on first input
            newForm.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            setTimeout(() => {
                const firstInput = newForm.querySelector('input:not([type="hidden"])') as HTMLInputElement;
                if (firstInput) {
                    firstInput.focus();
                }
            }, 300);
        }
    }

    private cloneExistingForm(container: HTMLElement, config: FormsetConfig, newFormIndex: number): HTMLElement | null {
        const existingForms = container.querySelectorAll(`.${config.formClass}:not([style*="display: none"])`);
        const lastForm = existingForms[existingForms.length - 1] as HTMLElement;

        if (!lastForm) return null;

        const newForm = lastForm.cloneNode(true) as HTMLElement;

        // Clear input values and update names/IDs
        newForm.querySelectorAll('input, textarea, select').forEach(input => {
            const element = input as HTMLInputElement;
            if (element.type !== 'hidden') {
                element.value = '';
                element.checked = false;
            }

            // Update name and id attributes
            if (element.name) {
                element.name = element.name.replace(/-\d+-/, `-${newFormIndex}-`);
            }
            if (element.id) {
                element.id = element.id.replace(/-\d+-/, `-${newFormIndex}-`);
            }
        });

        // Update labels
        newForm.querySelectorAll('label').forEach(label => {
            const forAttr = label.getAttribute('for');
            if (forAttr) {
                label.setAttribute('for', forAttr.replace(/-\d+-/, `-${newFormIndex}-`));
            }
        });

        // Remove any error messages
        newForm.querySelectorAll('.invalid-feedback').forEach(error => error.remove());

        // Ensure proper form visibility
        newForm.style.display = '';

        return newForm;
    }

    private createFormFromTemplate(formsetType: string, formIndex: number): HTMLElement {
        // Create form templates for empty formsets
        const templates: Record<string, HTMLElement> = {
            'supplier_contacts': this.createContactTemplate(formIndex),
            'authors': this.createAuthorTemplate(formIndex),
            'licenses': this.createLicenseTemplate(formIndex)
        };

        return templates[formsetType] || document.createElement('div');
    }

    private createContactTemplate(index: number): HTMLElement {
        const div = document.createElement('div');
        div.className = 'supplier-contact-form border rounded-3 p-4 mb-3 bg-light position-relative';
        div.innerHTML = `
            <div class="position-absolute top-0 end-0 m-3">
                <button type="button"
                        class="btn btn-outline-danger btn-sm remove-item-btn remove-contact-btn"
                        title="Remove Contact">
                    <i class="fas fa-trash"></i>
                </button>
            </div>
            <div class="row g-3">
                <div class="col-md-4">
                    <label for="id_supplier_contacts-${index}-name" class="form-label fw-semibold text-secondary">
                        Name <span class="text-danger ms-1">*</span>
                    </label>
                    <input type="text" name="supplier_contacts-${index}-name"
                           id="id_supplier_contacts-${index}-name"
                           class="form-control" placeholder="Contact name" required>
                </div>
                <div class="col-md-4">
                    <label for="id_supplier_contacts-${index}-email" class="form-label fw-semibold text-secondary">Email</label>
                    <input type="email" name="supplier_contacts-${index}-email"
                           id="id_supplier_contacts-${index}-email"
                           class="form-control" placeholder="contact@example.com">
                </div>
                <div class="col-md-4">
                    <label for="id_supplier_contacts-${index}-phone" class="form-label fw-semibold text-secondary">Phone</label>
                    <input type="text" name="supplier_contacts-${index}-phone"
                           id="id_supplier_contacts-${index}-phone"
                           class="form-control" placeholder="+1 (555) 123-4567">
                </div>
            </div>
        `;
        return div;
    }

    private createAuthorTemplate(index: number): HTMLElement {
        const div = document.createElement('div');
        div.className = 'author-form border rounded-3 p-4 mb-3 bg-light position-relative';
        div.innerHTML = `
            <div class="position-absolute top-0 end-0 m-3">
                <button type="button"
                        class="btn btn-outline-danger btn-sm remove-item-btn remove-author-btn"
                        title="Remove Author">
                    <i class="fas fa-trash"></i>
                </button>
            </div>
            <div class="row g-3">
                <div class="col-md-4">
                    <label for="id_authors-${index}-name" class="form-label fw-semibold text-secondary">
                        Name <span class="text-danger ms-1">*</span>
                    </label>
                    <input type="text" name="authors-${index}-name"
                           id="id_authors-${index}-name"
                           class="form-control" placeholder="Author name" required>
                </div>
                <div class="col-md-4">
                    <label for="id_authors-${index}-email" class="form-label fw-semibold text-secondary">Email</label>
                    <input type="email" name="authors-${index}-email"
                           id="id_authors-${index}-email"
                           class="form-control" placeholder="author@example.com">
                </div>
                <div class="col-md-4">
                    <label for="id_authors-${index}-phone" class="form-label fw-semibold text-secondary">Phone</label>
                    <input type="text" name="authors-${index}-phone"
                           id="id_authors-${index}-phone"
                           class="form-control" placeholder="+1 (555) 123-4567">
                </div>
            </div>
        `;
        return div;
    }

    private createLicenseTemplate(index: number): HTMLElement {
        const div = document.createElement('div');
        div.className = 'license-form border rounded-3 p-4 mb-4 bg-light position-relative';
        div.innerHTML = `
            <div class="position-absolute top-0 end-0 m-3">
                <button type="button"
                        class="btn btn-outline-danger btn-sm remove-item-btn remove-license-btn"
                        title="Remove License">
                    <i class="fas fa-trash"></i>
                </button>
            </div>
            <!-- License form content will be populated by initializeLicenseFormHandlers -->
            <div class="license-form-content">
                <!-- License Type Selection -->
                <div class="mb-4">
                    <label class="form-label fw-semibold text-secondary mb-3">
                        <i class="fas fa-tags me-2"></i>License Type
                    </label>
                    <div class="license-type-selection">
                        <div class="form-check mb-2">
                            <input class="form-check-input" type="radio" name="licenses-${index}-license_type"
                                   id="id_licenses-${index}-license_type_0" value="spdx">
                            <label class="form-check-label fw-medium" for="id_licenses-${index}-license_type_0">
                                SPDX License
                            </label>
                        </div>
                        <div class="form-check mb-2">
                            <input class="form-check-input" type="radio" name="licenses-${index}-license_type"
                                   id="id_licenses-${index}-license_type_1" value="expression">
                            <label class="form-check-label fw-medium" for="id_licenses-${index}-license_type_1">
                                License Expression
                            </label>
                        </div>
                        <div class="form-check mb-2">
                            <input class="form-check-input" type="radio" name="licenses-${index}-license_type"
                                   id="id_licenses-${index}-license_type_2" value="custom">
                            <label class="form-check-label fw-medium" for="id_licenses-${index}-license_type_2">
                                Custom License
                            </label>
                        </div>
                    </div>
                </div>

                <!-- License ID/Expression Field -->
                <div class="mb-3">
                    <label for="id_licenses-${index}-license_id" class="form-label fw-semibold text-secondary">
                        License ID or Expression
                    </label>
                    <input type="text" name="licenses-${index}-license_id"
                           id="id_licenses-${index}-license_id"
                           class="form-control" placeholder="e.g., MIT or MIT OR Apache-2.0">
                </div>

                <!-- SPDX Quick Select -->
                <div class="mb-4">
                    <label for="id_licenses-${index}-spdx_license_choice" class="form-label fw-semibold text-secondary">
                        Quick Select SPDX License
                    </label>
                    <div class="position-relative">
                        <input type="text" name="licenses-${index}-spdx_license_choice"
                               id="id_licenses-${index}-spdx_license_choice"
                               class="form-control spdx-license-autocomplete"
                               placeholder="Search for a license (e.g., MIT, Apache-2.0)..."
                               autocomplete="off">
                        <div class="dropdown-menu w-100 spdx-license-dropdown" style="max-height: 300px; overflow-y: auto;">
                        </div>
                    </div>
                </div>
            </div>
        `;
        return div;
    }

    private updateFormCounts(): void {
        // Update total form counts for all formsets
        Object.entries(this.formsetConfigs).forEach(([_type, config]) => {
            const container = document.querySelector(config.containerSelector);
            const totalFormsInput = document.querySelector(config.totalFormsSelector) as HTMLInputElement;

            if (container && totalFormsInput) {
                const visibleForms = container.querySelectorAll(`.${config.formClass}:not([style*="display: none"])`);
                totalFormsInput.value = visibleForms.length.toString();
            }
        });
    }

    private initializeLicenseAutocomplete(): void {
        // Initialize existing SPDX autocomplete inputs
        document.querySelectorAll('.spdx-license-autocomplete').forEach(input => {
            this.setupAutocompleteForInput(input as HTMLInputElement);
        });

        // Initialize existing license expression inputs
        document.querySelectorAll('input[name*="license_id"]').forEach(input => {
            this.setupExpressionAutocomplete(input as HTMLInputElement);
        });
    }

    private initializeLicenseFormHandlers(form?: HTMLElement): void {
        const forms = form ? [form] : document.querySelectorAll('.license-form');

        forms.forEach((licenseForm) => {
            // Initialize license type change handlers
            const typeRadios = licenseForm.querySelectorAll('input[name*="license_type"]');
            typeRadios.forEach(radio => {
                radio.addEventListener('change', () => {
                    this.handleLicenseTypeChange(radio as HTMLInputElement);
                });
            });

            // Initialize autocomplete for new forms
            const spdxAutocompleteInput = licenseForm.querySelector('.spdx-license-autocomplete') as HTMLInputElement;
            if (spdxAutocompleteInput && !this.licenseAutocompleteInstances.has(spdxAutocompleteInput)) {
                this.setupAutocompleteForInput(spdxAutocompleteInput);
            }

            // Initialize autocomplete for license expression field
            const expressionInput = licenseForm.querySelector('input[name*="license_id"]') as HTMLInputElement;
            if (expressionInput && !this.licenseAutocompleteInstances.has(expressionInput)) {
                this.setupExpressionAutocomplete(expressionInput);
            }
        });
    }

    private setupAutocompleteForInput(input: HTMLInputElement): void {
        if (this.licenseAutocompleteInstances.has(input)) return;

        this.licenseAutocompleteInstances.add(input);
        const dropdown = input.parentElement?.querySelector('.spdx-license-dropdown') as HTMLElement;

        if (!dropdown) return;

        // Input event listener
        input.addEventListener('input', (e) => {
            const query = (e.target as HTMLInputElement).value.trim();

            if (query.length >= 1) {
                this.filterLicenses(query, dropdown, input);
                dropdown.classList.add('show');
            } else {
                dropdown.classList.remove('show');
            }
        });

        // Focus event listener
        input.addEventListener('focus', (e) => {
            const query = (e.target as HTMLInputElement).value.trim();
            if (query.length >= 1) {
                this.filterLicenses(query, dropdown, input);
                dropdown.classList.add('show');
            }
        });

        // Hide dropdown when clicking outside
        document.addEventListener('click', (e) => {
            if (!input.contains(e.target as Node) && !dropdown.contains(e.target as Node)) {
                dropdown.classList.remove('show');
            }
        });
    }

    private filterLicenses(query: string, dropdown: HTMLElement, targetInput: HTMLInputElement): void {
        const data = window.licenseData || [];
        const filteredLicenses = data.filter(license =>
            license.key.toLowerCase().includes(query.toLowerCase()) ||
            license.name.toLowerCase().includes(query.toLowerCase())
        ).slice(0, 50);

        this.renderLicenseOptions(dropdown, filteredLicenses, targetInput);
    }

    private renderLicenseOptions(dropdown: HTMLElement, licenses: LicenseData[], targetInput: HTMLInputElement): void {
        dropdown.innerHTML = '';

        if (licenses.length === 0) {
            dropdown.innerHTML = '<div class="dropdown-item text-muted">No licenses found</div>';
            return;
        }

        licenses.forEach(license => {
            const item = document.createElement('div');
            item.className = 'dropdown-item cursor-pointer';
            item.innerHTML = `
                <div class="d-flex justify-content-between align-items-center">
                    <div>
                        <strong>${license.key}</strong>
                        <div class="text-muted small">${license.name}</div>
                    </div>
                    <small class="badge bg-secondary">${license.origin}</small>
                </div>
            `;

            item.addEventListener('click', () => {
                targetInput.value = license.key;
                dropdown.classList.remove('show');

                // Also update the license_id field
                const licenseIdField = targetInput.closest('.license-form')?.querySelector('input[name*="license_id"]') as HTMLInputElement;
                if (licenseIdField) {
                    licenseIdField.value = license.key;
                }
            });

            dropdown.appendChild(item);
        });
    }

    private handleLicenseTypeChange(radio: HTMLInputElement): void {
        const licenseForm = radio.closest('.license-form') as HTMLElement;
        const customSection = licenseForm.querySelector('.custom-license-section') as HTMLElement;

        if (customSection) {
            if (radio.value === 'custom') {
                customSection.style.display = 'block';
            } else {
                customSection.style.display = 'none';
            }
        }
    }

    private initializeLicenseTypeHandlers(): void {
        // Initialize existing license type handlers
        document.querySelectorAll('input[name*="license_type"]').forEach(radio => {
            radio.addEventListener('change', () => {
                this.handleLicenseTypeChange(radio as HTMLInputElement);
            });

            // Set initial state
            if ((radio as HTMLInputElement).checked) {
                this.handleLicenseTypeChange(radio as HTMLInputElement);
            }
        });
    }

    private showSuccessMessage(message: string): void {
        // Use global notification system if available
        if ((window as any).showSuccess) {
            (window as any).showSuccess(message);
        } else {
            // Fallback to console log
            console.log(message);
        }
    }

    // Supplier URL Management
    private supplierUrls: string[] = [];

    private initializeSupplierUrls(): void {
        const hiddenInput = document.querySelector('input[name="supplier_url"]') as HTMLInputElement;
        const container = document.getElementById('supplier-urls-container');
        const addButton = document.querySelector('.add-supplier-url-btn') as HTMLButtonElement;

        if (!hiddenInput || !container || !addButton) return;

        // Parse existing URLs from hidden input
        const existingUrls = hiddenInput.value.trim();

        // Handle edge cases: empty string, "[]", or actual URLs
        if (!existingUrls || existingUrls === '[]') {
            this.supplierUrls = [];
        } else {
            this.supplierUrls = existingUrls.split('\n').filter(url => url.trim() && url !== '[]');
        }

        // Render existing URLs
        this.renderSupplierUrls(container, hiddenInput);

        // Add button handler
        addButton.addEventListener('click', () => {
            this.addSupplierUrl(container, hiddenInput);
        });
    }

    private renderSupplierUrls(container: HTMLElement, hiddenInput: HTMLInputElement): void {
        container.innerHTML = '';

        if (this.supplierUrls.length === 0) {
            container.innerHTML = `
                <div class="supplier-url-empty-state text-muted p-3 border border-dashed rounded-3 bg-light">
                    <div class="text-center">
                        <i class="fas fa-link text-secondary mb-2" style="font-size: 1.5rem;"></i>
                        <p class="mb-0 small">No URLs added yet. Click "Add URL" below to get started.</p>
                    </div>
                </div>
            `;
            return;
        }

        this.supplierUrls.forEach((url, index) => {
            const urlItem = document.createElement('div');
            urlItem.className = 'supplier-url-item border rounded-3 p-3 mb-2 bg-light position-relative';
            urlItem.innerHTML = `
                <div class="d-flex align-items-start gap-3">
                    <div class="flex-grow-1">
                        <label class="form-label fw-semibold text-secondary mb-2 small">
                            <i class="fas fa-link me-1"></i>Supplier URL ${index + 1}
                        </label>
                        <input type="url"
                               class="form-control supplier-url-input"
                               value="${url}"
                               data-index="${index}"
                               placeholder="https://example.com"
                               required>
                        <div class="invalid-feedback">Please enter a valid URL starting with http:// or https://</div>
                    </div>
                    <div class="flex-shrink-0 mt-4">
                        <button type="button"
                                class="btn btn-outline-danger btn-sm remove-supplier-url-btn"
                                data-index="${index}"
                                title="Remove URL">
                            <i class="fas fa-trash"></i>
                        </button>
                    </div>
                </div>
            `;

            container.appendChild(urlItem);

            // Add event listeners for this URL item
            const input = urlItem.querySelector('.supplier-url-input') as HTMLInputElement;
            const removeBtn = urlItem.querySelector('.remove-supplier-url-btn') as HTMLButtonElement;

            input.addEventListener('input', (e) => {
                const target = e.target as HTMLInputElement;
                this.updateSupplierUrl(parseInt(target.dataset.index!), target.value, hiddenInput);
            });

            input.addEventListener('blur', (e) => {
                this.validateSupplierUrlInput(e.target as HTMLInputElement);
            });

            removeBtn.addEventListener('click', (e) => {
                const target = e.target as HTMLElement;
                const button = target.closest('.remove-supplier-url-btn') as HTMLButtonElement;
                const index = parseInt(button.dataset.index!);
                this.removeSupplierUrl(index, container, hiddenInput);
            });
        });
    }

    private addSupplierUrl(container: HTMLElement, hiddenInput: HTMLInputElement): void {
        this.supplierUrls.push('');
        this.renderSupplierUrls(container, hiddenInput);
        this.updateHiddenInput(hiddenInput);

        // Add visual feedback and focus on the new input
        setTimeout(() => {
            const newUrlItem = container.querySelector('.supplier-url-item:last-of-type') as HTMLElement;
            const newInput = newUrlItem?.querySelector('.supplier-url-input') as HTMLInputElement;

            if (newUrlItem && newInput) {
                newUrlItem.classList.add('form-added');
                setTimeout(() => {
                    newUrlItem.classList.remove('form-added');
                }, 600);

                newInput.focus();
            }
        }, 100);

        this.showSuccessMessage('URL field added successfully');
    }

    private removeSupplierUrl(index: number, container: HTMLElement, hiddenInput: HTMLInputElement): void {
        if (this.supplierUrls.length <= 1) {
            // Don't remove the last URL, just clear it
            this.supplierUrls[0] = '';
        } else {
            this.supplierUrls.splice(index, 1);
        }

        this.renderSupplierUrls(container, hiddenInput);
        this.updateHiddenInput(hiddenInput);
        this.showSuccessMessage('URL removed successfully');
    }

    private updateSupplierUrl(index: number, value: string, hiddenInput: HTMLInputElement): void {
        this.supplierUrls[index] = value;
        this.updateHiddenInput(hiddenInput);
    }

    private updateHiddenInput(hiddenInput: HTMLInputElement): void {
        const validUrls = this.supplierUrls.filter(url => url.trim());
        hiddenInput.value = validUrls.join('\n');
    }

    private setupExpressionAutocomplete(input: HTMLInputElement): void {
        if (this.licenseAutocompleteInstances.has(input)) return;

        this.licenseAutocompleteInstances.add(input);

        // Create dropdown container if it doesn't exist
        let dropdown = input.parentElement?.querySelector('.license-expression-dropdown') as HTMLElement;
        if (!dropdown) {
            dropdown = document.createElement('div');
            dropdown.className = 'dropdown-menu w-100 license-expression-dropdown';
            dropdown.style.cssText = 'max-height: 300px; overflow-y: auto; display: none;';
            input.parentElement?.appendChild(dropdown);
        }

        // Input event listener for expression autocomplete
        input.addEventListener('input', (e) => {
            const target = e.target as HTMLInputElement;
            const query = target.value.trim();
            const cursorPos = target.selectionStart || 0;

            // Check if we're typing a license identifier (after 'AND', 'OR', or at the beginning)
            const beforeCursor = query.substring(0, cursorPos);
            const lastToken = this.getLastIncompleteToken(beforeCursor);

            if (lastToken && lastToken.length >= 1) {
                this.filterLicensesForExpression(lastToken, dropdown, input, beforeCursor, cursorPos);
                dropdown.style.display = 'block';
            } else {
                dropdown.style.display = 'none';
            }
        });

        // Focus event listener
        input.addEventListener('focus', (e) => {
            const target = e.target as HTMLInputElement;
            const query = target.value.trim();
            const cursorPos = target.selectionStart || 0;
            const beforeCursor = query.substring(0, cursorPos);
            const lastToken = this.getLastIncompleteToken(beforeCursor);

            if (lastToken && lastToken.length >= 1) {
                this.filterLicensesForExpression(lastToken, dropdown, input, beforeCursor, cursorPos);
                dropdown.style.display = 'block';
            }
        });

        // Hide dropdown when clicking outside
        document.addEventListener('click', (e) => {
            if (!input.contains(e.target as Node) && !dropdown.contains(e.target as Node)) {
                dropdown.style.display = 'none';
            }
        });
    }

    private getLastIncompleteToken(text: string): string {
        // Match license expressions and return the last incomplete token
        const tokens = text.split(/\s+(AND|OR)\s+/i);
        const lastToken = tokens[tokens.length - 1]?.trim() || '';

        // If the last token looks like it's in parentheses, extract the content
        const parenMatch = lastToken.match(/\(([^)]*?)$/);
        if (parenMatch) {
            return parenMatch[1];
        }

        return lastToken;
    }

    private filterLicensesForExpression(query: string, dropdown: HTMLElement, targetInput: HTMLInputElement, beforeCursor: string, cursorPos: number): void {
        const data = window.licenseData || [];
        const filteredLicenses = data.filter(license =>
            license.key.toLowerCase().includes(query.toLowerCase()) ||
            license.name.toLowerCase().includes(query.toLowerCase())
        ).slice(0, 20); // Limit to 20 for expressions

        this.renderExpressionLicenseOptions(dropdown, filteredLicenses, targetInput, beforeCursor, cursorPos, query);
    }

    private renderExpressionLicenseOptions(dropdown: HTMLElement, licenses: LicenseData[], targetInput: HTMLInputElement, beforeCursor: string, cursorPos: number, query: string): void {
        dropdown.innerHTML = '';

        if (licenses.length === 0) {
            dropdown.innerHTML = '<div class="dropdown-item text-muted">No licenses found</div>';
            return;
        }

        licenses.forEach(license => {
            const item = document.createElement('div');
            item.className = 'dropdown-item cursor-pointer';
            item.innerHTML = `
                <div class="d-flex justify-content-between align-items-center">
                    <div>
                        <strong>${license.key}</strong>
                        <div class="text-muted small">${license.name}</div>
                    </div>
                    <small class="badge bg-secondary">${license.origin}</small>
                </div>
            `;

            item.addEventListener('click', () => {
                // Replace the last incomplete token with the selected license
                const beforeToken = beforeCursor.substring(0, beforeCursor.length - query.length);
                const afterCursor = targetInput.value.substring(cursorPos);
                const newValue = beforeToken + license.key + afterCursor;

                targetInput.value = newValue;
                dropdown.style.display = 'none';

                // Set cursor position after the inserted license
                const newCursorPos = beforeToken.length + license.key.length;
                targetInput.setSelectionRange(newCursorPos, newCursorPos);
                targetInput.focus();
            });

            dropdown.appendChild(item);
        });
    }

    private setupRealTimeValidation(form: HTMLElement): void {
        // Email validation
        const emailInputs = form.querySelectorAll('input[type="email"]') as NodeListOf<HTMLInputElement>;
        emailInputs.forEach(input => {
            input.addEventListener('blur', () => this.validateEmailInput(input));
            input.addEventListener('input', () => {
                // Clear validation classes on input to give immediate feedback
                input.classList.remove('is-invalid', 'is-valid');
            });
        });

        // URL validation
        const urlInputs = form.querySelectorAll('input[name*="url"], input[placeholder*="URL"], input[placeholder*="url"]') as NodeListOf<HTMLInputElement>;
        urlInputs.forEach(input => {
            input.addEventListener('blur', () => this.validateUrlInput(input));
            input.addEventListener('input', () => {
                input.classList.remove('is-invalid', 'is-valid');
            });
        });

        // Phone validation (basic format check)
        const phoneInputs = form.querySelectorAll('input[name*="phone"], input[type="tel"]') as NodeListOf<HTMLInputElement>;
        phoneInputs.forEach(input => {
            input.addEventListener('blur', () => this.validatePhoneInput(input));
            input.addEventListener('input', () => {
                input.classList.remove('is-invalid', 'is-valid');
            });
        });

        // Required field validation
        const requiredInputs = form.querySelectorAll('input[required], select[required], textarea[required]') as NodeListOf<HTMLInputElement>;
        requiredInputs.forEach(input => {
            input.addEventListener('blur', () => this.validateRequiredInput(input));
            input.addEventListener('input', () => {
                input.classList.remove('is-invalid', 'is-valid');
            });
        });

        // Enhanced keyboard navigation
        this.setupKeyboardNavigation(form);
    }

    private validateEmailInput(input: HTMLInputElement): void {
        const email = input.value.trim();
        const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
        const isValid = !email || emailRegex.test(email);

        this.updateValidationState(input, isValid);
        this.showValidationFeedback(input, isValid, 'Please enter a valid email address');
    }

    private validateUrlInput(input: HTMLInputElement): void {
        const url = input.value.trim();
        const isValid = !url || (url.startsWith('http://') || url.startsWith('https://'));

        this.updateValidationState(input, isValid);
        this.showValidationFeedback(input, isValid, 'URL must start with http:// or https://');
    }

    private validatePhoneInput(input: HTMLInputElement): void {
        const phone = input.value.trim();
        // Basic phone validation - allows various formats
        const phoneRegex = /^[\+]?[\d\s\-\(\)\.]{7,}$/;
        const isValid = !phone || phoneRegex.test(phone);

        this.updateValidationState(input, isValid);
        this.showValidationFeedback(input, isValid, 'Please enter a valid phone number');
    }

    private validateRequiredInput(input: HTMLInputElement): void {
        const isValid = input.value.trim() !== '';

        this.updateValidationState(input, isValid);
        this.showValidationFeedback(input, isValid, 'This field is required');
    }

    private updateValidationState(input: HTMLInputElement, isValid: boolean): void {
        if (isValid) {
            input.classList.remove('is-invalid');
            input.classList.add('is-valid');
        } else {
            input.classList.remove('is-valid');
            input.classList.add('is-invalid');
        }
    }

    private showValidationFeedback(input: HTMLInputElement, isValid: boolean, errorMessage: string): void {
        // Remove existing feedback
        const existingFeedback = input.parentElement?.querySelector('.invalid-feedback.real-time-feedback');
        if (existingFeedback) {
            existingFeedback.remove();
        }

        // Add error feedback if invalid
        if (!isValid && input.value.trim() !== '') {
            const feedback = document.createElement('div');
            feedback.className = 'invalid-feedback real-time-feedback d-block';
            feedback.textContent = errorMessage;
            input.parentElement?.appendChild(feedback);
        }
    }

    private setupKeyboardNavigation(form: HTMLElement): void {
        // Allow Tab/Shift+Tab to navigate between form elements
        const formElements = form.querySelectorAll('input, select, textarea, button') as NodeListOf<HTMLElement>;

        formElements.forEach((element, index) => {
            // Set proper tabindex for logical tab order
            if (!element.hasAttribute('tabindex')) {
                element.setAttribute('tabindex', '0');
            }

            // Handle Enter key on buttons
            if (element.tagName === 'BUTTON') {
                element.addEventListener('keydown', (e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault();
                        (element as HTMLButtonElement).click();
                    }
                });
            }

            // Handle navigation keys
            element.addEventListener('keydown', (e) => {
                this.handleNavigationKeys(e, formElements, index);
            });

            // Add ARIA attributes for better screen reader support
            if (element.tagName === 'INPUT' || element.tagName === 'TEXTAREA' || element.tagName === 'SELECT') {
                const label = form.querySelector(`label[for="${element.id}"]`);
                if (label && !element.hasAttribute('aria-label')) {
                    element.setAttribute('aria-describedby', element.id + '-description');
                }
            }
        });

        // Add remove button keyboard support
        const removeButtons = form.querySelectorAll('.remove-item-btn') as NodeListOf<HTMLButtonElement>;
        removeButtons.forEach(button => {
            button.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    button.click();
                }
            });
        });
    }

    private handleNavigationKeys(e: KeyboardEvent, formElements: NodeListOf<HTMLElement>, currentIndex: number): void {
        switch (e.key) {
            case 'ArrowDown':
            case 'Tab':
                if (!e.shiftKey) {
                    // Move to next element
                    e.preventDefault();
                    const nextIndex = (currentIndex + 1) % formElements.length;
                    formElements[nextIndex].focus();
                }
                break;
            case 'ArrowUp':
                if (!e.shiftKey) {
                    // Move to previous element
                    e.preventDefault();
                    const prevIndex = currentIndex === 0 ? formElements.length - 1 : currentIndex - 1;
                    formElements[prevIndex].focus();
                }
                break;
            case 'Escape':
                // Blur current element
                (e.target as HTMLElement).blur();
                break;
        }
    }

    private initializeRealTimeValidationForExistingForms(): void {
        // Apply real-time validation to all existing forms
        const existingForms = document.querySelectorAll('.supplier-contact-form, .author-form, .license-form');
        existingForms.forEach(form => {
            if (form instanceof HTMLElement) {
                this.setupRealTimeValidation(form);
            }
        });

        // Also apply to the main metadata form fields
        const metadataForm = document.querySelector('form');
        if (metadataForm) {
            this.setupRealTimeValidation(metadataForm);
        }
    }

    private validateSupplierUrlInput(input: HTMLInputElement): void {
        const url = input.value.trim();
        const isValid = !url || (url.startsWith('http://') || url.startsWith('https://'));

        if (isValid) {
            input.classList.remove('is-invalid');
            input.classList.add('is-valid');
        } else {
            input.classList.remove('is-valid');
            input.classList.add('is-invalid');
        }
    }

    private setupFormSubmissionHandling(): void {
        const form = document.querySelector('form') as HTMLFormElement;
        const submitButton = form?.querySelector('button[type="submit"]') as HTMLButtonElement;

        if (form && submitButton) {
            form.addEventListener('submit', (e) => {
                this.handleFormSubmission(e, form, submitButton);
            });
        }
    }

    private handleFormSubmission(e: SubmitEvent, form: HTMLFormElement, submitButton: HTMLButtonElement): void {
        // Show loading state
        this.setLoadingState(submitButton, true);

        // Disable all form elements to prevent double submission
        this.setFormDisabled(form, true);

        // Add a small delay to ensure user sees the loading state
        setTimeout(() => {
            // Form will submit naturally after this
        }, 100);

        // Set up a timeout to re-enable form if something goes wrong
        setTimeout(() => {
            this.setLoadingState(submitButton, false);
            this.setFormDisabled(form, false);
        }, 10000); // 10 second timeout
    }

    private setLoadingState(button: HTMLButtonElement, isLoading: boolean): void {
        if (isLoading) {
            button.disabled = true;
            button.innerHTML = `
                <span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>
                Saving Changes...
            `;
            button.setAttribute('aria-label', 'Saving metadata changes, please wait');
        } else {
            button.disabled = false;
            button.innerHTML = `
                <i class="fas fa-save me-2" aria-hidden="true"></i>Save Metadata
            `;
            button.setAttribute('aria-label', 'Save component metadata changes');
        }
    }

    private setFormDisabled(form: HTMLFormElement, disabled: boolean): void {
        const elements = form.querySelectorAll('input, select, textarea, button') as NodeListOf<HTMLElement>;
        elements.forEach(element => {
            if (element instanceof HTMLInputElement ||
                element instanceof HTMLSelectElement ||
                element instanceof HTMLTextAreaElement ||
                element instanceof HTMLButtonElement) {
                element.disabled = disabled;
            }
        });

        // Add visual feedback to the form
        if (disabled) {
            form.classList.add('form-submitting');
        } else {
            form.classList.remove('form-submitting');
        }
    }

    private showSaveProgress(): void {
        // Create or update progress indicator
        let progressIndicator = document.querySelector('.save-progress') as HTMLElement;

        if (!progressIndicator) {
            progressIndicator = document.createElement('div');
            progressIndicator.className = 'save-progress alert alert-info d-flex align-items-center';
            progressIndicator.innerHTML = `
                <div class="spinner-border spinner-border-sm me-3" role="status" aria-hidden="true"></div>
                <span>Saving your changes...</span>
            `;
            progressIndicator.setAttribute('role', 'status');
            progressIndicator.setAttribute('aria-live', 'polite');

            const form = document.querySelector('form');
            if (form) {
                form.insertAdjacentElement('afterbegin', progressIndicator);
            }
        }

        progressIndicator.style.display = 'flex';
    }

    private hideSaveProgress(): void {
        const progressIndicator = document.querySelector('.save-progress') as HTMLElement;
        if (progressIndicator) {
            progressIndicator.style.display = 'none';
        }
    }

    private initializeFormProgress(): void {
        this.createProgressIndicator();
        this.updateFormProgress();

        // Update progress when form fields change
        const form = document.querySelector('form');
        if (form) {
            form.addEventListener('input', () => {
                // Debounce progress updates
                clearTimeout(this.progressUpdateTimeout);
                this.progressUpdateTimeout = setTimeout(() => {
                    this.updateFormProgress();
                }, 300);
            });

            form.addEventListener('change', () => {
                this.updateFormProgress();
            });
        }
    }

    private progressUpdateTimeout: number = 0;

    private createProgressIndicator(): void {
        const progressContainer = document.createElement('div');
        progressContainer.className = 'form-progress-container';
        progressContainer.innerHTML = `
            <div class="form-progress-header d-flex justify-content-between align-items-center">
                <span class="form-progress-label">Form Completion</span>
                <span class="form-progress-percentage">0%</span>
            </div>
            <div class="progress">
                <div class="progress-bar progress-bar-striped progress-bar-animated"
                     role="progressbar"
                     style="width: 0%"
                     aria-valuenow="0"
                     aria-valuemin="0"
                     aria-valuemax="100">
                </div>
            </div>
            <div class="form-progress-details">
                <small class="text-muted">
                    Complete the form to enable saving
                </small>
            </div>
        `;

        // Insert at the top of the form
        const form = document.querySelector('form');
        if (form) {
            const firstChild = form.firstElementChild;
            if (firstChild) {
                form.insertBefore(progressContainer, firstChild);
            } else {
                form.appendChild(progressContainer);
            }
        }
    }

    private updateFormProgress(): void {
        const form = document.querySelector('form');
        if (!form) return;

        const allFields = form.querySelectorAll('input:not([type="hidden"]), select, textarea') as NodeListOf<HTMLElement>;
        const requiredFields = form.querySelectorAll('input[required], select[required], textarea[required]') as NodeListOf<HTMLElement>;

        let totalFields = allFields.length;
        let filledFields = 0;
        let requiredFilled = 0;
        let totalRequired = requiredFields.length;

        // Count filled fields
        allFields.forEach(field => {
            if (field instanceof HTMLInputElement || field instanceof HTMLTextAreaElement) {
                if (field.value.trim() !== '') {
                    filledFields++;
                }
            } else if (field instanceof HTMLSelectElement) {
                if (field.value !== '' && field.value !== null) {
                    filledFields++;
                }
            }
        });

        // Count filled required fields
        requiredFields.forEach(field => {
            if (field instanceof HTMLInputElement || field instanceof HTMLTextAreaElement) {
                if (field.value.trim() !== '') {
                    requiredFilled++;
                }
            } else if (field instanceof HTMLSelectElement) {
                if (field.value !== '' && field.value !== null) {
                    requiredFilled++;
                }
            }
        });

        // Calculate progress (weighted towards required fields)
        const requiredProgress = totalRequired > 0 ? (requiredFilled / totalRequired) * 70 : 70;
        const optionalProgress = totalFields > totalRequired ? ((filledFields - requiredFilled) / (totalFields - totalRequired)) * 30 : 0;
        const overallProgress = Math.min(100, requiredProgress + optionalProgress);

        this.updateProgressDisplay(overallProgress, requiredFilled, totalRequired, filledFields, totalFields);
    }

    private updateProgressDisplay(progress: number, requiredFilled: number, totalRequired: number, filledFields: number, totalFields: number): void {
        const progressBar = document.querySelector('.progress-bar') as HTMLElement;
        const progressPercentage = document.querySelector('.form-progress-percentage') as HTMLElement;
        const progressDetails = document.querySelector('.form-progress-details small') as HTMLElement;

        if (progressBar && progressPercentage && progressDetails) {
            // Update progress bar
            progressBar.style.width = `${progress}%`;
            progressBar.setAttribute('aria-valuenow', progress.toString());

            // Update percentage
            progressPercentage.textContent = `${Math.round(progress)}%`;

            // Update color based on progress
            progressBar.className = 'progress-bar progress-bar-striped';
            if (progress < 30) {
                progressBar.classList.add('bg-danger');
            } else if (progress < 70) {
                progressBar.classList.add('bg-warning');
            } else {
                progressBar.classList.add('bg-success');
                if (progress === 100) {
                    progressBar.classList.add('progress-bar-animated');
                }
            }

            // Update details text
            if (totalRequired > 0) {
                if (requiredFilled < totalRequired) {
                    progressDetails.innerHTML = `
                        <i class="fas fa-exclamation-circle text-warning me-1"></i>
                        ${totalRequired - requiredFilled} required field${totalRequired - requiredFilled !== 1 ? 's' : ''} remaining
                    `;
                } else {
                    progressDetails.innerHTML = `
                        <i class="fas fa-check-circle text-success me-1"></i>
                        All required fields completed! ${filledFields}/${totalFields} total fields filled
                    `;
                }
            } else {
                progressDetails.innerHTML = `
                    <i class="fas fa-info-circle text-info me-1"></i>
                    ${filledFields}/${totalFields} fields completed
                `;
            }
        }
    }
}

// Initialize when DOM is ready - only on pages that have metadata forms
document.addEventListener('DOMContentLoaded', () => {
    // Only initialize if we're on a page that has metadata formsets
    const metadataForm = document.querySelector('[data-metadata-form]') ||
                        document.querySelector('.metadata-formset') ||
                        document.querySelector('#component-metadata-form');

    if (metadataForm) {
        new MetadataFormsetManager();
    }
});

export { MetadataFormsetManager };
