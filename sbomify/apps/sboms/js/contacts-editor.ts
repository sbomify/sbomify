import Alpine from '../../core/js/alpine-init';
import type { ContactInfo } from '../../core/js/types';
import { ComponentEvents, addComponentEventListener } from '../../core/js/events';

interface ContactsEditorProps {
    contacts: ContactInfo[];
    contactType: string;
}

// More permissive email validation - backend is source of truth
// This allows common formats like user+tag@domain.co.uk
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
        cleanupEventListeners: [] as Array<() => void>,

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

            // Listen for metadata loaded events
            this.cleanupEventListeners.push(
                addComponentEventListener(ComponentEvents.METADATA_LOADED, (e) => {
                    const detail = e.detail as {
                        authors?: ContactInfo[];
                        supplier?: { contacts?: ContactInfo[] };
                    };
                    if (this.contactType === 'author' && detail?.authors) {
                        const newAuthors = Array.isArray(detail.authors) ? detail.authors : [];
                        if (JSON.stringify(newAuthors) !== JSON.stringify(this.contacts)) {
                            this.initializeContacts(newAuthors);
                        }
                    } else if (this.contactType === 'contact' && detail?.supplier?.contacts) {
                        const newContacts = Array.isArray(detail.supplier.contacts) ? detail.supplier.contacts : [];
                        if (JSON.stringify(newContacts) !== JSON.stringify(this.contacts)) {
                            this.initializeContacts(newContacts);
                        }
                    }
                })
            );

            // Listen for contact update events
            this.cleanupEventListeners.push(
                addComponentEventListener(ComponentEvents.CONTACTS_UPDATED, (e) => {
                    const detail = e.detail as { contacts?: ContactInfo[] };
                    if (this.contactType === 'author' && detail?.contacts) {
                        this.initializeContacts(detail.contacts);
                    }
                })
            );
        },

        destroy() {
            // Clean up all event listeners
            this.cleanupEventListeners.forEach(cleanup => cleanup());
            this.cleanupEventListeners = [];
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
