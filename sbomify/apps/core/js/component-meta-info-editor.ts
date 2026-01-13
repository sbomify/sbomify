import Alpine from './alpine-init';
import { getCsrfToken } from './csrf';
import type { ContactProfile, ComponentMetaInfo } from './types';
import {
    ComponentEvents,
    dispatchComponentEvent,
    type MetadataLoadedEvent,
    type ContactsUpdatedEvent,
    type MetadataUpdatedEvent,
    type ShowAlertEvent
} from './events';

interface LifecyclePhase {
    value: string;
    label: string;
}

interface ComponentMetaInfoEditorProps {
    componentId: string;
    teamKey: string;
    metadata: ComponentMetaInfo | null;
    contactProfiles: ContactProfile[];
}

const LIFECYCLE_ORDER = [
    "design",
    "pre-build",
    "build",
    "post-build",
    "operations",
    "discovery",
    "decommission"
];

const formatLifecyclePhase = (phase: string): string => {
    if (phase === 'pre-build') return 'Pre-Build';
    if (phase === 'post-build') return 'Post-Build';
    return phase.charAt(0).toUpperCase() + phase.slice(1);
};

export function registerComponentMetaInfoEditor() {
    Alpine.data('componentMetaInfoEditor', (props: ComponentMetaInfoEditorProps) => ({
        componentId: props.componentId,
        teamKey: props.teamKey,
        metadata: props.metadata || {
            id: '',
            name: '',
            supplier: { name: null, url: [], address: null, contacts: [] },
            authors: [],
            licenses: [],
            lifecycle_phase: null,
            contact_profile_id: null,
            contact_profile: null,
            uses_custom_contact: true
        } as ComponentMetaInfo,
        contactProfiles: props.contactProfiles || [],
        selectedProfileId: props.metadata?.contact_profile_id || '',
        validationErrors: {
            supplier: {} as Record<string, string>,
            authors: {} as Record<string, string>,
            licenses: {} as Record<string, string>,
            lifecycle_phase: null as string | null
        },
        isSaving: false,
        hasUnsavedChanges: false,
        isInitializing: true,
        originalMetadata: null as string | null,
        boundHandleBeforeUnload: null as ((e: BeforeUnloadEvent) => void) | null,

        lifecyclePhases: LIFECYCLE_ORDER.map(phase => ({
            value: phase,
            label: formatLifecyclePhase(phase)
        })) as LifecyclePhase[],

        get isUsingProfile(): boolean {
            return this.metadata.contact_profile_id !== null && this.metadata.contact_profile_id !== '';
        },

        get selectedProfile(): ContactProfile | null {
            if (!this.metadata.contact_profile_id) return null;
            return this.contactProfiles.find(p => p.id === this.metadata.contact_profile_id) ||
                this.metadata.contact_profile || null;
        },

        get allContactProfiles(): ContactProfile[] {
            const profiles = [...this.contactProfiles];
            // Add unavailable profile if it exists and is not in the list
            if (this.selectedProfile && !profiles.some(p => p.id === this.selectedProfile?.id)) {
                profiles.push(this.selectedProfile);
            }
            return profiles;
        },

        getProfileDisplayText(profile: ContactProfile | null): string {
            if (!profile) return '';
            return profile.name || '';
        },

        getProfileOptionText(profile: ContactProfile): string {
            const isUnavailable = !this.contactProfiles.some(p => p.id === profile.id);
            return isUnavailable ? `${profile.name} (unavailable)` : profile.name;
        },

        get isFormValid(): boolean {
            const hasSupplierErrors = Object.keys(this.validationErrors.supplier).length > 0;
            const hasAuthorErrors = Object.keys(this.validationErrors.authors).length > 0;
            const hasLicenseErrors = Object.keys(this.validationErrors.licenses).length > 0;
            const hasLifecycleErrors = this.validationErrors.lifecycle_phase !== null;
            return !hasSupplierErrors && !hasAuthorErrors && !hasLicenseErrors && !hasLifecycleErrors;
        },

        init() {
            this.originalMetadata = JSON.stringify(this.metadata);
            this.boundHandleBeforeUnload = this.handleBeforeUnload.bind(this);
            window.addEventListener('beforeunload', this.boundHandleBeforeUnload);

            // Start async loads without blocking Alpine initialization
            this.$nextTick(() => {
                this.loadMetadata();
                this.loadContactProfiles();
            });
        },

        handleBeforeUnload(e: BeforeUnloadEvent) {
            if (this.hasUnsavedChanges) {
                e.preventDefault();
                e.returnValue = '';
            }
        },

        async loadMetadata() {
            try {
                const response = await fetch(`/api/v1/components/${this.componentId}/metadata`);
                if (response.ok) {
                    const data = await response.json();
                    this.metadata = {
                        ...this.metadata,
                        ...data,
                        supplier: data.supplier || { name: null, url: [], address: null, contacts: [] },
                        authors: data.authors || [],
                        licenses: data.licenses || []
                    };
                    this.selectedProfileId = this.metadata.contact_profile_id || '';
                    this.originalMetadata = JSON.stringify(this.metadata);

                    dispatchComponentEvent<MetadataLoadedEvent>(ComponentEvents.METADATA_LOADED, {
                        metadata: this.metadata,
                        licenses: this.metadata.licenses,
                        supplier: this.metadata.supplier,
                        authors: this.metadata.authors
                    });

                    this.hasUnsavedChanges = false;
                    this.isInitializing = false;
                    
                    // Sync authors from profile if needed (after metadata is loaded)
                    this.syncAuthorsFromProfile();
                } else {
                    console.error(`Failed to load metadata: ${response.status} ${response.statusText}`);
                    this.isInitializing = false;
                }
            } catch (error) {
                console.error('Failed to load metadata:', error);
                dispatchComponentEvent<ShowAlertEvent>(ComponentEvents.SHOW_ALERT, {
                    type: 'error',
                    message: 'Failed to load component metadata'
                });
                this.isInitializing = false;
            }
        },

        async loadContactProfiles() {
            if (!this.teamKey) {
                console.warn('Team key is not available, skipping contact profiles load');
                this.contactProfiles = [];
                return;
            }

            try {
                const response = await fetch(`/api/v1/workspaces/${this.teamKey}/contact-profiles`);
                if (response.ok) {
                    const data = await response.json();
                    this.contactProfiles = data || [];

                    // If there's a selected profile from metadata that's not in the list, add it
                    if (this.metadata.contact_profile && !this.contactProfiles.some(p => p.id === this.metadata.contact_profile?.id)) {
                        this.contactProfiles.push(this.metadata.contact_profile);
                    }

                    if (this.metadata.contact_profile_id) {
                        this.selectedProfileId = this.metadata.contact_profile_id;
                        this.syncAuthorsFromProfile();
                    }
                } else if (response.status === 403) {
                    this.contactProfiles = [];
                } else {
                    console.error(`Failed to load contact profiles: ${response.status} ${response.statusText}`);
                    this.contactProfiles = [];
                }
            } catch (error) {
                console.error('Failed to load contact profiles:', error);
                this.contactProfiles = [];
            }
        },

        /**
         * Synchronizes authors from the selected profile to component metadata.
         * This ensures components using a profile have the profile's authors loaded.
         * Only syncs if metadata.authors is empty to avoid overwriting manual edits.
         */
        syncAuthorsFromProfile() {
            if (!this.metadata.contact_profile_id || !this.contactProfiles.length) {
                return;
            }

            const profile = this.contactProfiles.find(p => p.id === this.metadata.contact_profile_id);
            if (!profile?.authors?.length) {
                return;
            }

            // Only sync if authors are empty (backwards compatibility for legacy components)
            if (!this.metadata.authors || this.metadata.authors.length === 0) {
                // Use JSON serialization instead of structuredClone due to DataCloneError
                // with complex author objects. Authors are simple JSON-serializable objects.
                this.metadata.authors = JSON.parse(JSON.stringify(profile.authors));
                
                // Use $nextTick to ensure component is ready to receive events
                this.$nextTick(() => {
                    dispatchComponentEvent<ContactsUpdatedEvent>(ComponentEvents.CONTACTS_UPDATED, {
                        contacts: this.metadata.authors
                    });
                });
            }
        },

        handleProfileChange() {
            const nextId = this.selectedProfileId || null;
            this.metadata.contact_profile_id = nextId;
            this.metadata.uses_custom_contact = nextId === null;
            this.hasUnsavedChanges = true;

            if (nextId === null) {
                this.metadata.contact_profile = null;
                if (this.metadata.supplier) {
                    this.metadata.supplier.name = null;
                }
                this.metadata.authors = [];
                this.$nextTick(() => {
                    dispatchComponentEvent<ContactsUpdatedEvent>(ComponentEvents.CONTACTS_UPDATED, {
                        contacts: []
                    });
                });
            } else {
                const profile = this.contactProfiles.find(p => p.id === nextId);
                this.metadata.contact_profile = profile || null;
                this.validationErrors.supplier = {};

                if (profile) {
                    // Use JSON serialization instead of structuredClone due to DataCloneError.
                    // Authors are simple objects (name, email, phone) suitable for JSON cloning.
                    const authors = profile.authors ? JSON.parse(JSON.stringify(profile.authors)) : [];
                    this.metadata.authors = authors;
                    this.$nextTick(() => {
                        dispatchComponentEvent<ContactsUpdatedEvent>(ComponentEvents.CONTACTS_UPDATED, {
                            contacts: authors
                        });
                    });
                }
            }
        },

        isValidUrl(url: string): boolean {
            try {
                new URL(url);
                return true;
            } catch {
                return false;
            }
        },

        isValidEmail(email: string): boolean {
            if (!email) return true;
            const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
            return emailRegex.test(email);
        },

        handleCancel() {
            if (this.hasUnsavedChanges) {
                const modalEl = document.getElementById('unsavedChangesModal');
                if (modalEl && window.bootstrap) {
                    try {
                        const modal = new window.bootstrap.Modal(modalEl);
                        modal.show();
                        return;
                    } catch (e) {
                        console.error('Failed to show modal', e);
                    }
                }

                // Fallback to confirm if modal fails
                if (!confirm('You have unsaved changes. Are you sure you want to cancel?')) {
                    return;
                }
            }
            this.$dispatch('close-editor');
        },

        discardChanges() {
            const modalEl = document.getElementById('unsavedChangesModal');
            if (modalEl && window.bootstrap) {
                const modal = window.bootstrap.Modal.getInstance(modalEl);
                modal?.hide();
            }
            this.$dispatch('close-editor');
        },

        async updateMetaData() {
            if (!this.isFormValid || this.isSaving) return;

            this.isSaving = true;

            try {
                const payload = {
                    supplier: this.metadata.supplier,
                    authors: this.metadata.authors,
                    licenses: this.metadata.licenses,
                    lifecycle_phase: this.metadata.lifecycle_phase,
                    contact_profile_id: this.metadata.contact_profile_id,
                    uses_custom_contact: this.metadata.uses_custom_contact
                };

                const response = await fetch(`/api/v1/components/${this.componentId}/metadata`, {
                    method: 'PATCH',
                    headers: {
                        'X-CSRFToken': getCsrfToken(),
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify(payload)
                });

                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({}));
                    throw new Error(errorData.detail || `HTTP ${response.status}`);
                }

                this.hasUnsavedChanges = false;
                this.originalMetadata = JSON.stringify(this.metadata);
                this.$dispatch('metadata-saved');
                
                dispatchComponentEvent<MetadataUpdatedEvent>(ComponentEvents.METADATA_UPDATED, {
                    componentId: this.componentId
                });
                dispatchComponentEvent<ShowAlertEvent>(ComponentEvents.SHOW_ALERT, {
                    type: 'success',
                    message: 'Metadata saved successfully'
                });
            } catch (error) {
                console.error('Save error:', error);
                dispatchComponentEvent<ShowAlertEvent>(ComponentEvents.SHOW_ALERT, {
                    type: 'error',
                    message: error instanceof Error ? error.message : 'Failed to save metadata'
                });
            } finally {
                this.isSaving = false;
            }
        },

        destroy() {
            if (this.boundHandleBeforeUnload) {
                window.removeEventListener('beforeunload', this.boundHandleBeforeUnload);
                this.boundHandleBeforeUnload = null;
            }
        }
    }));
}
