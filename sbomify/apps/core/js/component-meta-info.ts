import Alpine from './alpine-init';
import { getCsrfToken } from './csrf';
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
            uses_custom_contact: true
        } as ComponentMetaInfo,
        showEditButton: props.allowEdit, // Alias for template binding
        isEmpty: isEmpty, // Helper

        init() {
            this.fetchMetadata();

            this.cleanupEventListeners.push(
                addComponentEventListener('item-selected', (e) => {
                    const detail = e.detail as { itemId: string };
                    this.copyMetadataFrom(detail.itemId);
                })
            );

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
                    if (this.metadata.contact_profile_id && this.metadata.contact_profile?.authors) {
                        // Use JSON serialization instead of structuredClone due to DataCloneError
                        // with complex author objects. Authors are simple JSON-serializable objects
                        // (name, email, phone) without functions, symbols, or circular references.
                        const profileAuthors = JSON.parse(JSON.stringify(this.metadata.contact_profile.authors));
                        
                        // Only update if authors have actually changed
                        if (JSON.stringify(this.metadata.authors) !== JSON.stringify(profileAuthors)) {
                            this.metadata.authors = profileAuthors;
                        }
                    } else if (this.metadata.contact_profile_id && !this.metadata.contact_profile?.authors) {
                        // Profile has no authors, clear component authors
                        if (this.metadata.authors?.length > 0) {
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

        openCopyModal() {
            const modalEl = document.getElementById('itemSelectModal');
            if (modalEl) {
                // Dispatch event to Alpine component on modal to open it
                window.dispatchEvent(new CustomEvent('open-item-select-modal', {
                    detail: { excludeItems: [this.componentId] }
                }));

                // Use Bootstrap API to show
                const modal = new window.bootstrap.Modal(modalEl);
                modal.show();
            }
        },

        async copyMetadataFrom(sourceId: string) {
            try {
                // 1. Get source metadata
                const sourceResponse = await fetch(`/api/v1/components/${sourceId}/metadata`);
                if (!sourceResponse.ok) throw new Error('Failed to get source metadata');
                const sourceMetadata = await sourceResponse.json();

                // 2. Prepare payload (exclude id, name)
                const metadataToCopy = { ...sourceMetadata };
                delete metadataToCopy.id;
                delete metadataToCopy.name;

                // 3. Patch target
                const targetResponse = await fetch(`/api/v1/components/${this.componentId}/metadata`, {
                    method: 'PATCH',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': getCsrfToken()
                    },
                    body: JSON.stringify(metadataToCopy)
                });

                if (!targetResponse.ok) throw new Error('Failed to update target metadata');

                this.refreshDisplay();
                dispatchComponentEvent<ShowAlertEvent>(ComponentEvents.SHOW_ALERT, {
                    type: 'success',
                    message: 'Metadata copied successfully'
                });

            } catch (error) {
                console.error('Failed to copy metadata:', error);
                dispatchComponentEvent<ShowAlertEvent>(ComponentEvents.SHOW_ALERT, {
                    type: 'error',
                    message: error instanceof Error ? error.message : 'Failed to copy metadata'
                });
            }
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


    // --- Item Select Modal Component ---
    interface ModalProps {
        itemType: string;
        excludeItems?: string[];
    }

    interface PaginationMeta {
        total_pages: number;
        total_items: number;
        page: number;
        page_size: number;
    }

    Alpine.data('itemSelectModal', (props: ModalProps) => ({
        itemType: props.itemType,
        excludeItems: props.excludeItems || [],
        items: [] as Array<{ team_key: string; team_name: string; item_key: string; item_name: string }>,
        isLoading: false,
        selectedItemId: '',

        // Pagination
        currentPage: 1,
        pageSize: 15,
        paginationMeta: null as PaginationMeta | null,

        init() {
            this.$watch('currentPage', () => this.loadItems());
            this.$watch('pageSize', () => {
                this.currentPage = 1;
                this.loadItems()
            });
        },

        openModal(detail?: { excludeItems?: string[] }) {
            if (detail?.excludeItems) {
                this.excludeItems = detail.excludeItems;
            }
            this.selectedItemId = '';
            this.currentPage = 1;
            this.loadItems();
        },

        closeModal() {
            this.items = [];
        },

        async loadItems() {
            this.isLoading = true;
            try {
                const params = new URLSearchParams({
                    page: this.currentPage.toString(),
                    page_size: this.pageSize.toString()
                });
                const response = await fetch(`/api/v1/${this.itemType}s?${params}`);
                if (!response.ok) throw new Error('Failed to fetch items');

                const data = await response.json();
                const itemsData = data.items || data;
                this.paginationMeta = data.pagination || null;

                // Transform
                const transformedItems = itemsData.map((item: { team_id: string; id: string; name: string }) => ({
                    team_key: item.team_id,
                    team_name: 'Current Workspace',
                    item_key: item.id,
                    item_name: item.name
                }));

                if (this.excludeItems.length > 0) {
                    this.items = transformedItems.filter((i: { item_key: string }) => !this.excludeItems.includes(i.item_key));
                } else {
                    this.items = transformedItems;
                }

            } catch (error) {
                console.error(error);
            } finally {
                this.isLoading = false;
            }
        },

        confirmSelection() {
            if (this.selectedItemId) {
                window.dispatchEvent(new CustomEvent('item-selected', {
                    detail: { itemId: this.selectedItemId }
                }));

                // Close modal
                const el = document.getElementById('itemSelectModal');
                if (el) {
                    const modal = window.bootstrap.Modal.getInstance(el);
                    modal?.hide();
                }
            }
        },

        // Pagination helper for template
        goToPage(page: number) {
            if (page >= 1 && (!this.paginationMeta || page <= this.paginationMeta.total_pages)) {
                this.currentPage = page;
            }
        }
    }));
}
