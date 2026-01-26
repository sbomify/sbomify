import Alpine from 'alpinejs';
import { scrollTo } from '../../../core/js/components/scroll-to';

interface ContactEntitySnapshot {
    name: string;
    email: string;
    phone: string;
    address: string;
    websites: string;
    isManufacturer: boolean;
    isSupplier: boolean;
    isAuthor: boolean;
}

/**
 * Contact Entity Component
 * Handles individual entity (manufacturer/supplier/author) within a contact profile
 */
export function registerContactEntity(): void {
    Alpine.data('contactEntity', (prefix: string) => {
        return {
            prefix,
            name: '',
            email: '',
            phone: '',
            address: '',
            websites: '',
            isManufacturer: true,
            isSupplier: true,
            isAuthor: true,
            deleted: false,
            activeContactsCount: 0,
            contacts: [] as Array<{ name: string; isAuthor: boolean; isSecurityContact: boolean; isTechnicalContact: boolean }>,
            touched: false,
            contactsTouched: false,
            editing: false,
            isNew: false,
            snapshot: null as ContactEntitySnapshot | null,

            get isAuthorOnly(): boolean {
                return this.isAuthor && !this.isManufacturer && !this.isSupplier;
            },

            get countTriggerKey(): string {
                // Computed property that changes when any count-relevant property changes
                // Used with x-effect to trigger updateContactCount
                return `${this.deleted}-${this.isManufacturer}-${this.isSupplier}-${this.isAuthor}-${this.editing}`;
            },

            init() {
                const nameInput = this.$el.querySelector(`input[name="${prefix}-name"]`) as HTMLInputElement;
                if (nameInput) this.name = nameInput.value.trim();

                const emailInput = this.$el.querySelector(`input[name="${prefix}-email"]`) as HTMLInputElement;
                if (emailInput) this.email = emailInput.value.trim();

                const phoneInput = this.$el.querySelector(`input[name="${prefix}-phone"]`) as HTMLInputElement;
                if (phoneInput) this.phone = phoneInput.value.trim();

                const addressInput = this.$el.querySelector(`textarea[name="${prefix}-address"]`) as HTMLTextAreaElement;
                if (addressInput) this.address = addressInput.value.trim();

                const webInput = this.$el.querySelector(`textarea[name="${prefix}-website_urls_text"]`) as HTMLTextAreaElement;
                if (webInput) this.websites = webInput.value;

                // Read initial roles from checkboxes (scoped to this component)
                const mfgCheckbox = this.$el.querySelector(`input[name="${prefix}-is_manufacturer"]`) as HTMLInputElement;
                const supCheckbox = this.$el.querySelector(`input[name="${prefix}-is_supplier"]`) as HTMLInputElement;
                const authorCheckbox = this.$el.querySelector(`input[name="${prefix}-is_author"]`) as HTMLInputElement;

                this.isNew = !this.name && !this.isAuthor;

                if (!this.isNew) {
                    // For existing entities, read from checkboxes
                    if (mfgCheckbox) this.isManufacturer = mfgCheckbox.checked;
                    if (supCheckbox) this.isSupplier = supCheckbox.checked;
                    if (authorCheckbox) this.isAuthor = authorCheckbox.checked;
                } else {
                    // For new entities, default to available roles
                    const parent = this.$el.closest('.profile-form') || this.$el.closest('.component-metadata-formset');
                    const formData = parent ? window.Alpine.$data(parent as HTMLElement) : null;
                    if (formData && ((formData as { manufacturerCount?: number }).manufacturerCount! > 0 || (formData as { supplierCount?: number }).supplierCount! > 0)) {
                        this.isManufacturer = (formData as { manufacturerCount?: number }).manufacturerCount! < 1;
                        this.isSupplier = (formData as { supplierCount?: number }).supplierCount! < 1;
                    } else {
                        this.isManufacturer = true;
                        this.isSupplier = true;
                    }
                    this.isAuthor = true;
                }

                // Watch editing for snapshot creation (needs old value check, so keep $watch)
                this.$watch('editing', (value: boolean) => {
                    if (value && !this.snapshot) {
                        this.createSnapshot();
                    }
                    if (!value) {
                        this.updateContactCount();
                    }
                });

                this.updateContactCount();

                this.$nextTick(() => {
                    window.dispatchEvent(new CustomEvent('update-counts'));
                });
            },

            get canSelectManufacturer() {
                const parent = this.$el.closest('.profile-form') || this.$el.closest('.component-metadata-formset');
                if (!parent) return true;
                const formData = window.Alpine.$data(parent as HTMLElement);
                if (!formData) return true;
                const formDataTyped = formData as { manufacturerCount?: number };
                if (this.isNew) {
                    return (formDataTyped.manufacturerCount || 0) < 1;
                }
                return (formDataTyped.manufacturerCount || 0) < 1 || this.isManufacturer;
            },

            get canSelectSupplier() {
                const parent = this.$el.closest('.profile-form') || this.$el.closest('.component-metadata-formset');
                if (!parent) return true;
                const formData = window.Alpine.$data(parent as HTMLElement);
                if (!formData) return true;
                const formDataTyped = formData as { supplierCount?: number };
                if (this.isNew) {
                    return (formDataTyped.supplierCount || 0) < 1;
                }
                return (formDataTyped.supplierCount || 0) < 1 || this.isSupplier;
            },

            get hasErrors() {
                if (this.deleted) return false;
                if (!this.isManufacturer && !this.isSupplier && !this.isAuthor) return true;
                if (!this.isAuthorOnly) {
                    if (!this.name || !this.email || !this.isValidEmail(this.email)) return true;
                }
                return this.activeContactsCount === 0;
            },

            isValidEmail(email: string): boolean {
                if (!email) return false;
                const input = document.createElement('input');
                input.type = 'email';
                input.value = email;
                return input.checkValidity();
            },

            createSnapshot() {
                this.snapshot = {
                    name: this.name,
                    email: this.email,
                    phone: this.phone,
                    address: this.address,
                    websites: this.websites,
                    isManufacturer: this.isManufacturer,
                    isSupplier: this.isSupplier,
                    isAuthor: this.isAuthor
                };
            },

            saveEdit() {
                this.touched = true;
                this.contactsTouched = true;

                const nameInput = this.$el.querySelector(`input[name="${prefix}-name"]`) as HTMLInputElement;
                const emailInput = this.$el.querySelector(`input[name="${prefix}-email"]`) as HTMLInputElement;

                // For non-author-only entities, name and email are required
                if (!this.isAuthorOnly) {
                    if (nameInput && !this.name) {
                        nameInput.focus();
                        nameInput.reportValidity();
                        return;
                    }

                    if (emailInput) {
                        emailInput.value = this.email || '';

                        if (!this.email) {
                            emailInput.setCustomValidity('Please enter an email address');
                            emailInput.focus();
                            emailInput.reportValidity();
                            const clearValidity = () => {
                                emailInput.setCustomValidity('');
                                emailInput.removeEventListener('input', clearValidity);
                            };
                            emailInput.addEventListener('input', clearValidity);
                            return;
                        }

                        if (!this.isValidEmail(this.email)) {
                            emailInput.setCustomValidity('Please enter a valid email address (e.g., contact@example.com)');
                            emailInput.focus();
                            emailInput.reportValidity();
                            const clearValidity = () => {
                                emailInput.setCustomValidity('');
                                emailInput.removeEventListener('input', clearValidity);
                            };
                            emailInput.addEventListener('input', clearValidity);
                            return;
                        }

                        emailInput.setCustomValidity('');
                    }
                }

                // Validate at least one role is selected
                if (!this.isManufacturer && !this.isSupplier && !this.isAuthor) {
                    this.touched = true;
                    const roleSection = this.$el.querySelector('.role-selection');
                    if (roleSection) {
                        scrollTo(roleSection as HTMLElement, { behavior: 'smooth', block: 'center' });
                        const firstCheckbox = roleSection.querySelector('input[type="checkbox"]') as HTMLInputElement;
                        if (firstCheckbox) {
                            firstCheckbox.setCustomValidity('Please select at least one role (Manufacturer, Supplier, or Author)');
                            firstCheckbox.focus();
                            firstCheckbox.reportValidity();
                            const clearValidity = () => {
                                firstCheckbox.setCustomValidity('');
                                firstCheckbox.removeEventListener('change', clearValidity);
                            };
                            firstCheckbox.addEventListener('change', clearValidity);
                        }
                    }
                    return;
                }

                // CycloneDX requirement: at least one contact per entity
                this.updateContactCount();
                if (this.activeContactsCount === 0) {
                    const addContactBtn = this.$el.querySelector('.add-contact-btn') as HTMLButtonElement;
                    if (addContactBtn) {
                        addContactBtn.setCustomValidity('Please add at least one contact person for this entity');
                        addContactBtn.focus();
                        addContactBtn.reportValidity();
                        const clearValidity = () => {
                            (addContactBtn as HTMLButtonElement).setCustomValidity('');
                            addContactBtn.removeEventListener('click', clearValidity);
                        };
                        addContactBtn.addEventListener('click', clearValidity);
                    }
                    return;
                }

                const contactPrefix = `${prefix}-contacts`;
                const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
                let hasContactError = false;

                document.querySelectorAll(`input[name^="${contactPrefix}-"][name$="-name"]`).forEach(contactNameInput => {
                    if (hasContactError) return;

                    const contactCard = (contactNameInput as HTMLElement).closest('.contact-card') as HTMLElement;
                    if (!contactCard) return;

                    const contactEmailInput = contactCard.querySelector('input[name$="-email"]') as HTMLInputElement;
                    const deleteInput = contactCard.querySelector('input[name$="-DELETE"]') as HTMLInputElement;

                    const isDeleted = deleteInput && deleteInput.value === 'true';
                    const isHidden = contactCard.style.display === 'none' || !contactCard.offsetParent;

                    if (isDeleted || isHidden) return;

                    const contactNameValue = (contactNameInput as HTMLInputElement).value.trim();
                    const contactEmailValue = contactEmailInput ? contactEmailInput.value.trim() : '';

                    // Validate name is required
                    if (!contactNameValue) {
                        (contactNameInput as HTMLInputElement).setCustomValidity('Name is required for this contact');
                        (contactNameInput as HTMLInputElement).focus();
                        (contactNameInput as HTMLInputElement).reportValidity();
                        const clearValidity = () => {
                            (contactNameInput as HTMLInputElement).setCustomValidity('');
                            (contactNameInput as HTMLInputElement).removeEventListener('input', clearValidity);
                        };
                        (contactNameInput as HTMLInputElement).addEventListener('input', clearValidity);
                        hasContactError = true;
                        return;
                    }

                    // Validate email is required
                    if (!contactEmailValue) {
                        contactEmailInput.setCustomValidity('Email is required for this contact');
                        contactEmailInput.focus();
                        contactEmailInput.reportValidity();
                        const clearValidity = () => {
                            contactEmailInput.setCustomValidity('');
                            contactEmailInput.removeEventListener('input', clearValidity);
                        };
                        contactEmailInput.addEventListener('input', clearValidity);
                        hasContactError = true;
                        return;
                    }

                    // Validate email format
                    if (!emailRegex.test(contactEmailValue)) {
                        contactEmailInput.setCustomValidity('Please enter a valid email address');
                        contactEmailInput.focus();
                        contactEmailInput.reportValidity();
                        const clearValidity = () => {
                            contactEmailInput.setCustomValidity('');
                            contactEmailInput.removeEventListener('input', clearValidity);
                        };
                        contactEmailInput.addEventListener('input', clearValidity);
                        hasContactError = true;
                        return;
                    }

                    (contactNameInput as HTMLInputElement).setCustomValidity('');
                    if (contactEmailInput) {
                        contactEmailInput.setCustomValidity('');
                    }
                });

                if (hasContactError) {
                    return;
                }

                document.querySelectorAll(`input[name^="${contactPrefix}-"][name$="-name"]`).forEach(nameInput => {
                    const contactCard = (nameInput as HTMLElement).closest('.contact-card') as HTMLElement;
                    if (!contactCard) return;

                    const emailInput = contactCard.querySelector('input[name$="-email"]') as HTMLInputElement;
                    const deleteInput = contactCard.querySelector('input[name$="-DELETE"]') as HTMLInputElement;

                    const nameValue = (nameInput as HTMLInputElement).value.trim();
                    const emailValue = emailInput ? emailInput.value.trim() : '';
                    const isDeleted = deleteInput && deleteInput.value === 'true';
                    const isHidden = contactCard.style.display === 'none' || !contactCard.offsetParent;

                    if (!nameValue && !emailValue && !isDeleted) {
                        if (deleteInput) {
                            deleteInput.value = 'true';
                        }
                        contactCard.querySelectorAll('input[required]').forEach(input => {
                            input.removeAttribute('required');
                        });
                        contactCard.style.display = 'none';
                    }

                    if (isDeleted || isHidden) {
                        contactCard.querySelectorAll('input[required]').forEach(input => {
                            input.removeAttribute('required');
                        });
                    }
                });

                this.isNew = false;
                this.snapshot = null;
                this.editing = false;

                this.$nextTick(() => this.updateContactCount());
            },

            cancelEdit() {
                if (this.snapshot) {
                    this.name = this.snapshot.name;
                    this.email = this.snapshot.email;
                    this.phone = this.snapshot.phone;
                    this.address = this.snapshot.address;
                    this.websites = this.snapshot.websites;
                    this.isManufacturer = this.snapshot.isManufacturer;
                    this.isSupplier = this.snapshot.isSupplier;
                    this.isAuthor = this.snapshot.isAuthor;
                }
                if (this.isNew) {
                    this.deleted = true;
                    document.querySelectorAll(`input[name^="${prefix}-"][required]`).forEach(input => {
                        input.removeAttribute('required');
                    });
                }
                this.snapshot = null;
                this.editing = false;
                this.touched = false;
                this.contactsTouched = false;
            },

            removeEntity() {
                const entityName = this.name || 'this entity';
                if (typeof window.showDeleteConfirmation === 'function') {
                    window.showDeleteConfirmation(entityName, () => {
                        this.deleted = true;
                        this.editing = false;
                        document.querySelectorAll(`input[name^="${prefix}-"][required]`).forEach(input => {
                            input.removeAttribute('required');
                        });
                        window.dispatchEvent(new CustomEvent('update-counts'));
                    });
                }
            },

            addContact() {
                const listContainer = this.$el.querySelector('.contacts-list') as HTMLElement;
                if (listContainer && typeof window.addContactRow === 'function') {
                    window.addContactRow(listContainer, prefix);
                    this.$nextTick(() => {
                        this.updateContactCount();
                    });
                }
            },

            updateContactCount() {
                if (this.deleted) {
                    this.activeContactsCount = 0;
                    this.contacts = [];
                    return;
                }
                this.$nextTick(() => {
                    const list = this.$el.querySelector('.contacts-list') as HTMLElement;
                    if (list) {
                        const cards = list.querySelectorAll('.contact-card');
                        let count = 0;
                        const contactsData: Array<{ name: string; isAuthor: boolean; isSecurityContact: boolean; isTechnicalContact: boolean }> = [];
                        cards.forEach(card => {
                            const deleteInput = card.querySelector('input[name$="-DELETE"]') as HTMLInputElement;
                            if (!deleteInput || deleteInput.value !== 'true') {
                                count++;
                                const alpineData = window.Alpine.$data(card as HTMLElement);
                                if (alpineData) {
                                    const contactData = alpineData as { name?: string; isAuthor?: boolean; isSecurityContact?: boolean; isTechnicalContact?: boolean };
                                    contactsData.push({
                                        name: contactData.name || '',
                                        isAuthor: contactData.isAuthor || false,
                                        isSecurityContact: contactData.isSecurityContact || false,
                                        isTechnicalContact: contactData.isTechnicalContact || false
                                    });
                                }
                            }
                        });
                        this.activeContactsCount = count;
                        this.contacts = contactsData;
                    }
                });
            }
        };
    });
}
