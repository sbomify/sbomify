import Alpine from 'alpinejs';

/**
 * Contact Entry Component
 * Handles individual contact within an entity
 */
export function registerContactEntry(): void {
    Alpine.data('contactEntry', () => {
        return {
            deleted: false,
            isNew: true,
            name: '',
            email: '',
            isAuthor: false,
            isSecurityContact: false,
            isTechnicalContact: false,

            get securityContactDisabled() {
                let hasOtherSecurityContact = false;
                document.querySelectorAll('.contact-card').forEach(card => {
                    if (card === this.$el) return;
                    const alpineData = window.Alpine.$data(card as HTMLElement);
                    if (alpineData) {
                        const contactData = alpineData as { deleted?: boolean; isSecurityContact?: boolean };
                        if (!contactData.deleted && contactData.isSecurityContact) {
                            hasOtherSecurityContact = true;
                        }
                    }
                });
                return hasOtherSecurityContact;
            },

            get editing() {
                const parent = this.$el.closest('.entity-card') as HTMLElement;
                if (!parent) return false;
                try {
                    const parentData = window.Alpine.$data(parent as HTMLElement);
                    return parentData ? (parentData as { editing?: boolean }).editing || false : false;
                } catch {
                    return false;
                }
            },

            init() {
                const nameInput = this.$el.querySelector('input[name$="-name"]') as HTMLInputElement;
                const emailInput = this.$el.querySelector('input[name$="-email"]') as HTMLInputElement;
                const authorCheckbox = this.$el.querySelector('input[name$="-is_author"]') as HTMLInputElement;
                const securityCheckbox = this.$el.querySelector('input[name$="-is_security_contact"]') as HTMLInputElement;
                const technicalCheckbox = this.$el.querySelector('input[name$="-is_technical_contact"]') as HTMLInputElement;

                if (nameInput) {
                    this.name = nameInput.value.trim();
                    this.isNew = !this.name;
                    nameInput.addEventListener('input', () => {
                        this.name = nameInput.value.trim();
                        this.$dispatch('contact-updated');
                    });
                    nameInput.addEventListener('blur', () => this.checkEmpty());
                }

                if (emailInput) {
                    this.email = emailInput.value.trim();
                    emailInput.addEventListener('input', () => {
                        this.email = emailInput.value.trim();
                    });
                    emailInput.addEventListener('blur', () => this.checkEmpty());
                }

                if (authorCheckbox) {
                    this.isAuthor = authorCheckbox.checked;
                    authorCheckbox.addEventListener('change', () => {
                        this.isAuthor = authorCheckbox.checked;
                        this.$dispatch('contact-updated');
                    });
                }
                if (securityCheckbox) {
                    this.isSecurityContact = securityCheckbox.checked;
                    securityCheckbox.addEventListener('change', () => {
                        this.isSecurityContact = securityCheckbox.checked;
                        this.$dispatch('contact-updated');
                    });
                }
                if (technicalCheckbox) {
                    this.isTechnicalContact = technicalCheckbox.checked;
                    technicalCheckbox.addEventListener('change', () => {
                        this.isTechnicalContact = technicalCheckbox.checked;
                        this.$dispatch('contact-updated');
                    });
                }
            },

            get isEmpty() {
                return !this.name && !this.email;
            },

            checkEmpty() {
                if (this.isNew && this.isEmpty) {
                    this.$nextTick(() => {
                        setTimeout(() => {
                            if (this.isEmpty && !this.$el.contains(document.activeElement)) {
                                this.removeContact();
                            }
                        }, 200);
                    });
                }
            },

            removeContact() {
                this.deleted = true;
                this.$el.querySelectorAll('input, select, textarea').forEach(input => {
                    (input as HTMLInputElement).setCustomValidity('');
                    input.removeAttribute('required');
                });
                this.$dispatch('contact-removed');
            }
        };
    });
}
