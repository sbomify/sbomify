import Alpine from './alpine-init';
import { isEmpty } from './utils';
import type { ComponentMetaInfo } from './types';
import { ComponentEvents, addComponentEventListener, dispatchComponentEvent, type ShowAlertEvent } from './events';

interface WrapperProps {
    componentId: string;
    teamKey: string;
    allowEdit: boolean;
}

export function registerComponentMetaInfo() {
    Alpine.data('componentMetaInfoWrapper', (props: WrapperProps) => ({
        componentId: props.componentId,
        teamKey: props.teamKey,
        allowEdit: props.allowEdit,
        isEditing: false,
        cleanupEventListeners: [] as Array<() => void>,

        // Display Component State (lifted up or shared via events, but here managed locally for display reactivity)
        metadata: {
            id: '',
            name: '',
            supplier: {
                name: null,
                url: [],
                address: null,
                contacts: []
            },
            authors: [],
            licenses: [],
            lifecycle_phase: null,
            contact_profile_id: null,
            contact_profile: null,
            uses_custom_contact: true,
            // Lifecycle event fields (aligned with Common Lifecycle Enumeration)
            release_date: null,
            end_of_support: null,
            end_of_life: null
        } as ComponentMetaInfo,
        showEditButton: props.allowEdit, // Alias for template binding
        isEmpty: isEmpty, // Helper

        init() {
            this.fetchMetadata();

            this.cleanupEventListeners.push(
                addComponentEventListener(ComponentEvents.METADATA_UPDATED, (e) => {
                    const detail = e.detail as { componentId: string };
                    if (detail.componentId === this.componentId) {
                        this.refreshDisplay();
                    }
                })
            );
        },

        destroy() {
            this.cleanupEventListeners.forEach(cleanup => cleanup());
            this.cleanupEventListeners = [];
        },

        async fetchMetadata() {
            try {
                const response = await fetch(`/api/v1/components/${this.componentId}/metadata`);
                if (response.ok) {
                    const data = await response.json();
                    this.metadata = { ...this.metadata, ...data };
                    
                    // Always sync authors from profile when a profile is selected
                    // This ensures the display shows the latest authors from the profile
                    if (this.metadata.contact_profile_id && this.metadata.contact_profile?.authors?.length) {
                        // Use JSON serialization instead of structuredClone due to DataCloneError
                        // with complex author objects. Authors are simple JSON-serializable objects
                        // (name, email, phone) without functions, symbols, or circular references.
                        const profileAuthors = JSON.parse(JSON.stringify(this.metadata.contact_profile.authors));
                        
                        // Only update if authors have actually changed
                        // Handle undefined/null case for metadata.authors
                        const currentAuthors = this.metadata.authors ?? [];
                        if (JSON.stringify(currentAuthors) !== JSON.stringify(profileAuthors)) {
                            this.metadata.authors = profileAuthors;
                        }
                    } else if (this.metadata.contact_profile_id && !this.metadata.contact_profile?.authors?.length) {
                        // Profile has no authors (handles both undefined/null and empty array), clear component authors
                        if (this.metadata.authors?.length) {
                            this.metadata.authors = [];
                        }
                    }
                } else {
                    console.error(`Failed to fetch metadata: ${response.status} ${response.statusText}`);
                    dispatchComponentEvent<ShowAlertEvent>(ComponentEvents.SHOW_ALERT, {
                        type: 'error',
                        message: 'Failed to load component metadata'
                    });
                }
            } catch (error) {
                console.error('Failed to fetch metadata', error);
                dispatchComponentEvent<ShowAlertEvent>(ComponentEvents.SHOW_ALERT, {
                    type: 'error',
                    message: 'Network error loading metadata'
                });
            }
        },

        refreshDisplay() {
            this.isEditing = false;
            this.fetchMetadata();
            dispatchComponentEvent<ShowAlertEvent>(ComponentEvents.SHOW_ALERT, {
                type: 'success',
                message: 'Metadata updated successfully'
            });
        },

        // Display Component Helpers
        hasSupplierInfo() {
            return this.metadata.supplier?.name || this.metadata.supplier?.url || this.metadata.supplier?.address;
        },

        getLifecyclePhaseClass(phase: string): string {
            switch (phase) {
                case 'design':
                    return 'lifecycle-badge-design';
                case 'pre-build':
                    return 'lifecycle-badge-pre-build';
                case 'build':
                    return 'lifecycle-badge-build';
                case 'post-build':
                    return 'lifecycle-badge-post-build';
                case 'operations':
                    return 'lifecycle-badge-operations';
                case 'discovery':
                    return 'lifecycle-badge-discovery';
                case 'decommission':
                    return 'lifecycle-badge-decommission';
                default:
                    return 'lifecycle-badge-design';
            }
        },

        formatLifecyclePhase(phase: string): string {
            if (phase === 'pre-build') return 'Pre-Build';
            if (phase === 'post-build') return 'Post-Build';
            return phase.charAt(0).toUpperCase() + phase.slice(1);
        },

        async removeSupplierContact(index: number) {
            if (!this.metadata.supplier?.contacts) return;
            this.metadata.supplier.contacts.splice(index, 1);
        },

        async removeAuthor(index: number) {
            if (!this.metadata.authors) return;
            this.metadata.authors.splice(index, 1);
        }
    }));
}
