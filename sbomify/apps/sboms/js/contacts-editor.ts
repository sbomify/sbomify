import Alpine from '../../core/js/alpine-init';
import type { ContactInfo } from '../../core/js/types';

interface ContactsEditorProps {
    contacts: ContactInfo[];
    contactType: string;
}

const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function registerContactsEditor() {
    Alpine.data('contactsEditor', (props: ContactsEditorProps) => ({
        contacts: [] as ContactInfo[],
        contactType: props.contactType || 'contact',
        addingContact: false,
        newContact: {
            name: '',
            email: '',
            phone: ''
        } as ContactInfo,
        formErrors: {} as Record<string, string>,
        boundMetadataLoadedHandler: null as ((e: Event) => void) | null,

        get capitalizedContactType(): string {
            if (!this.contactType) return '';
            return this.contactType.charAt(0).toUpperCase() + this.contactType.slice(1);
        },

        get addButtonText(): string {
            const base = `Add ${this.capitalizedContactType}`;
            return this.contacts.length > 0 ? `${base} another` : base;
        },

        init() {
            this.initializeContacts(props.contacts || []);

            let previousContacts = JSON.stringify(this.contacts);
            this.$watch('contacts', () => {
                const current = JSON.stringify(this.contacts);
                if (current !== previousContacts) {
                    previousContacts = current;
                    this.dispatchUpdate();
                }
            });

            this.boundMetadataLoadedHandler = (e: Event) => {
                const detail = (e as CustomEvent).detail;
                if (this.contactType === 'author' && detail && detail.authors) {
                    const newAuthors = Array.isArray(detail.authors) ? detail.authors : [];
                    if (JSON.stringify(newAuthors) !== JSON.stringify(this.contacts)) {
                        this.initializeContacts(newAuthors);
                    }
                } else if (this.contactType === 'contact' && detail && detail.supplier && detail.supplier.contacts) {
                    const newContacts = Array.isArray(detail.supplier.contacts) ? detail.supplier.contacts : [];
                    if (JSON.stringify(newContacts) !== JSON.stringify(this.contacts)) {
                        this.initializeContacts(newContacts);
                    }
                }
            };
            window.addEventListener('component-metadata-loaded', this.boundMetadataLoadedHandler);
        },

        destroy() {
            if (this.boundMetadataLoadedHandler) {
                window.removeEventListener('component-metadata-loaded', this.boundMetadataLoadedHandler);
                this.boundMetadataLoadedHandler = null;
            }
        },

        initializeContacts(contacts: ContactInfo[]) {
            // Similar to licenses editor's initializeTags - completely replace the array
            // Use direct assignment like licenses editor does
            this.contacts = Array.isArray(contacts) ? contacts.map(c => ({ ...c })) : [];
        },

        startAddContact() {
            this.formErrors = {};
            this.addingContact = true;
            this.$nextTick(() => {
                const nameInput = this.$refs.nameInput as HTMLInputElement;
                nameInput?.focus();
            });
        },

        isValidEmail(email: string): boolean {
            if (!email) return true;
            return EMAIL_REGEX.test(email);
        },

        validateForm(): boolean {
            this.formErrors = {};

            // Name is required
            if (!this.newContact.name?.trim()) {
                this.formErrors.name = 'Name is required';
            }

            // Email is optional but must be valid if provided
            if (this.newContact.email && !this.isValidEmail(this.newContact.email)) {
                this.formErrors.email = 'Please enter a valid email address';
            }

            return Object.keys(this.formErrors).length === 0;
        },

        saveContact() {
            if (!this.validateForm()) return;

            this.contacts.push({ ...this.newContact });
            this.dispatchUpdate();

            this.newContact = {
                name: '',
                email: '',
                phone: ''
            };
            this.formErrors = {};

            if (this.contacts.length === 1) {
                this.addingContact = false;
            }
        },

        cancelAddContact() {
            this.addingContact = false;
            this.newContact = {
                name: '',
                email: '',
                phone: ''
            };
            this.formErrors = {};
        },

        removeContact(index: number) {
            this.contacts.splice(index, 1);
            this.dispatchUpdate();
        },

        dispatchUpdate() {
            this.$dispatch('contacts-updated', { contacts: this.contacts });
        }
    }));
}
