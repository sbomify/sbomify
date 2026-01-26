import Alpine from 'alpinejs';
import { scrollTo } from '../../../core/js/components/scroll-to';

/**
 * Contact Profile Form Component
 * Handles form submission and entity management for contact profiles
 */
export function registerContactProfileForm(): void {
    Alpine.data('contactProfileForm', (entitiesPrefix: string) => {
        return {
            entitiesPrefix,
            visibleEntitiesCount: 0,
            manufacturerCount: 0,
            supplierCount: 0,
            isInitialized: false,

            init() {
                this.$nextTick(() => {
                    this.isInitialized = true;
                    this.updateCounts();
                });
            },

            initForm() {
                // Legacy method - can be removed
                this.updateCounts();
            },

            get hasErrors() {
                return document.querySelectorAll('.is-invalid').length > 0;
            },

            addEntity() {
                const container = document.getElementById('entities-container');
                const totalFormsInput = document.querySelector(`input[name="${this.entitiesPrefix}-TOTAL_FORMS"]`) as HTMLInputElement;
                if (!container || !totalFormsInput) return;

                const currentCount = parseInt(totalFormsInput.value);
                const templateEl = document.getElementById('entity-template') as HTMLTemplateElement;
                const template = templateEl?.content.cloneNode(true) as DocumentFragment;
                if (!template) return;

                const newRow = document.createElement('div');
                newRow.appendChild(template);

                const newHtml = newRow.innerHTML.replace(/__prefix__/g, currentCount.toString());
                newRow.innerHTML = newHtml;

                const entityPrefix = `${this.entitiesPrefix}-${currentCount}`;
                const contactPrefix = `${entityPrefix}-contacts`;

                const mgmtDiv = document.createElement('div');
                mgmtDiv.innerHTML = `
                    <input type="hidden" name="${contactPrefix}-TOTAL_FORMS" value="0" id="id_${contactPrefix}-TOTAL_FORMS">
                    <input type="hidden" name="${contactPrefix}-INITIAL_FORMS" value="0" id="id_${contactPrefix}-INITIAL_FORMS">
                    <input type="hidden" name="${contactPrefix}-MIN_NUM_FORMS" value="0" id="id_${contactPrefix}-MIN_NUM_FORMS">
                    <input type="hidden" name="${contactPrefix}-MAX_NUM_FORMS" value="1000" id="id_${contactPrefix}-MAX_NUM_FORMS">
                `;
                const contactsList = newRow.querySelector('.contacts-list');
                if (contactsList) {
                    contactsList.insertBefore(mgmtDiv, contactsList.firstChild);
                }

                container.appendChild(newRow.firstElementChild as Node);
                const newEntityEl = container.lastElementChild as HTMLElement;

                totalFormsInput.value = (currentCount + 1).toString();

                if (window.Alpine) {
                    window.Alpine.initTree(newEntityEl);
                }

                this.updateCounts();

                if (newEntityEl) {
                    const alpineData = window.Alpine.$data(newEntityEl);
                    if (alpineData) {
                        (alpineData as { editing?: boolean }).editing = true;
                    }
                    scrollTo(newEntityEl, { behavior: 'smooth', block: 'start' });
                }
            },

            submitForm(e: Event) {
                e.preventDefault();

                // Find the form - try multiple strategies
                let form = this.$el.querySelector('form') as HTMLFormElement;
                if (!form && e.target) {
                    form = (e.target as HTMLElement).closest('form') as HTMLFormElement;
                }
                if (!form) {
                    form = document.querySelector('.profile-form form') as HTMLFormElement;
                }
                if (!form) {
                    form = document.querySelector('.component-metadata-formset form') as HTMLFormElement;
                }

                if (!form) {
                    console.error('[submitForm] Could not find form element');
                    return;
                }

                // First, remove 'required' from deleted/hidden items before validation
                const isElementVisible = (el: HTMLElement | null): boolean => {
                    if (!el) return false;
                    const style = window.getComputedStyle(el);
                    return style.display !== 'none' &&
                        style.visibility !== 'hidden' &&
                        el.offsetParent !== null;
                };

                document.querySelectorAll('.entity-card').forEach(card => {
                    const deleteInput = card.querySelector('input[name$="-DELETE"]') as HTMLInputElement;
                    const isDeleted = deleteInput && deleteInput.value === 'true';
                    const isVisible = isElementVisible(card as HTMLElement);

                    if (isDeleted || !isVisible) {
                        card.querySelectorAll('input[required]').forEach(input => {
                            input.removeAttribute('required');
                        });
                    }
                });

                document.querySelectorAll('.contact-card').forEach(card => {
                    const deleteInput = card.querySelector('input[name$="-DELETE"]') as HTMLInputElement;
                    const isDeleted = deleteInput && deleteInput.value === 'true';
                    const isVisible = isElementVisible(card as HTMLElement);

                    if (isDeleted || !isVisible) {
                        card.querySelectorAll('input[required]').forEach(input => {
                            input.removeAttribute('required');
                        });
                    }
                });

                // Mark entities as touched for custom validation display
                document.querySelectorAll('.entity-card').forEach(card => {
                    const alpineData = window.Alpine.$data(card as HTMLElement);
                    if (alpineData && !(alpineData as { deleted?: boolean }).deleted) {
                        (alpineData as { touched?: boolean; contactsTouched?: boolean; updateContactCount?: () => void }).touched = true;
                        (alpineData as { contactsTouched?: boolean }).contactsTouched = true;
                        const updateCount = (alpineData as { updateContactCount?: () => void }).updateContactCount;
                        if (updateCount) updateCount();
                    }
                });

                // ORDERED VALIDATION - Check each field in specific order

                // 1. Validate Profile Name first (only for contact profile forms, not component metadata)
                const profileNameInput = form.querySelector('input[name="name"]') as HTMLInputElement;
                if (profileNameInput && !profileNameInput.checkValidity()) {
                    profileNameInput.reportValidity();
                    profileNameInput.focus();
                    return;
                }

                // 2. Validate Entities in order (role, name, email, contacts)
                const entityCards = Array.from(document.querySelectorAll('.entity-card'));
                for (const card of entityCards) {
                    const alpineData = window.Alpine.$data(card as HTMLElement);
                    if (!alpineData) continue;
                    const entityData = alpineData as { deleted?: boolean; isManufacturer?: boolean; isSupplier?: boolean; isAuthor?: boolean; isAuthorOnly?: boolean; activeContactsCount?: number; editing?: boolean };
                    if (entityData.deleted) continue;

                    // 2a. Check entity role (at least one must be selected)
                    if (!entityData.isManufacturer && !entityData.isSupplier && !entityData.isAuthor) {
                        scrollTo(card as HTMLElement, { behavior: 'smooth', block: 'center' });
                        return;
                    }

                    // 2b. Check entity name (only required for non-author-only entities)
                    if (!entityData.isAuthorOnly) {
                        const nameInput = card.querySelector('input[name$="-name"]') as HTMLInputElement;
                        if (nameInput && !nameInput.checkValidity()) {
                            scrollTo(card as HTMLElement, { behavior: 'smooth', block: 'center' });
                            nameInput.reportValidity();
                            nameInput.focus();
                            return;
                        }

                        // 2c. Check entity email (only required for non-author-only entities)
                        const emailInput = card.querySelector('input[name$="-email"]') as HTMLInputElement;
                        if (emailInput && !emailInput.checkValidity()) {
                            scrollTo(card as HTMLElement, { behavior: 'smooth', block: 'center' });
                            emailInput.reportValidity();
                            emailInput.focus();
                            return;
                        }
                    }

                    // 2d. Check entity has at least one contact
                    if (entityData.activeContactsCount === 0) {
                        entityData.editing = true;
                        scrollTo(card as HTMLElement, { behavior: 'smooth', block: 'center' });
                        return;
                    }

                    // 2e. Validate contacts within this entity
                    const contactCards = card.querySelectorAll('.contact-card');
                    for (const contactCard of contactCards) {
                        const deleteInput = contactCard.querySelector('input[name$="-DELETE"]') as HTMLInputElement;
                        const isDeleted = deleteInput && deleteInput.value === 'true';
                        if (isDeleted || !isElementVisible(contactCard as HTMLElement)) continue;

                        // Check contact name
                        const contactName = contactCard.querySelector('input[name$="-name"]') as HTMLInputElement;
                        if (contactName && !contactName.checkValidity()) {
                            scrollTo(card as HTMLElement, { behavior: 'smooth', block: 'center' });
                            contactName.reportValidity();
                            contactName.focus();
                            return;
                        }

                        // Check contact email
                        const contactEmail = contactCard.querySelector('input[name$="-email"]') as HTMLInputElement;
                        if (contactEmail && !contactEmail.checkValidity()) {
                            scrollTo(card as HTMLElement, { behavior: 'smooth', block: 'center' });
                            contactEmail.reportValidity();
                            contactEmail.focus();
                            return;
                        }
                    }
                }

                // All validation passed, trigger HTMX submission
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                if (typeof (window as any).htmx !== 'undefined') {
                    // eslint-disable-next-line @typescript-eslint/no-explicit-any
                    (window as any).htmx.trigger(form, 'htmx:submit');
                }
            },

            updateCounts() {
                let visibleEntities = 0;
                let mfgCount = 0;
                let supCount = 0;

                document.querySelectorAll('.entity-card').forEach(card => {
                    const alpineData = window.Alpine.$data(card as HTMLElement);
                    if (alpineData) {
                        const entityData = alpineData as { deleted?: boolean; isNew?: boolean; editing?: boolean; isManufacturer?: boolean; isSupplier?: boolean };
                        if (!entityData.deleted) {
                            visibleEntities++;
                            // Only count roles for saved entities (not new ones being edited)
                            if (!entityData.isNew || !entityData.editing) {
                                if (entityData.isManufacturer) mfgCount++;
                                if (entityData.isSupplier) supCount++;
                            }
                        }
                    }
                });

                this.visibleEntitiesCount = visibleEntities;
                this.manufacturerCount = mfgCount;
                this.supplierCount = supCount;
            }
        };
    });
}
