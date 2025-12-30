import Alpine from './alpine-init';
import { getCsrfToken } from './csrf';
import { isEmpty } from './utils';
import type { ComponentMetaInfo } from './types';

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
        boundItemSelectedHandler: null as ((e: Event) => void) | null,
        boundMetadataUpdatedHandler: null as ((e: Event) => void) | null,

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

            this.boundItemSelectedHandler = (e: Event) => {
                this.copyMetadataFrom((e as CustomEvent).detail.itemId);
            };
            this.boundMetadataUpdatedHandler = (e: Event) => {
                if ((e as CustomEvent).detail.componentId === this.componentId) {
                    this.refreshDisplay();
                }
            };

            window.addEventListener('item-selected', this.boundItemSelectedHandler);
            window.addEventListener('component-metadata-updated', this.boundMetadataUpdatedHandler);
        },

        destroy() {
            if (this.boundItemSelectedHandler) {
                window.removeEventListener('item-selected', this.boundItemSelectedHandler);
                this.boundItemSelectedHandler = null;
            }
            if (this.boundMetadataUpdatedHandler) {
                window.removeEventListener('component-metadata-updated', this.boundMetadataUpdatedHandler);
                this.boundMetadataUpdatedHandler = null;
            }
        },

        async fetchMetadata() {
            try {
                const response = await fetch(`/api/v1/components/${this.componentId}/metadata`);
                if (response.ok) {
                    const data = await response.json();
                    this.metadata = { ...this.metadata, ...data };
                }
            } catch (error) {
                console.error('Failed to fetch metadata', error);
            }
        },

        refreshDisplay() {
            this.isEditing = false;
            this.fetchMetadata();
            window.dispatchEvent(new CustomEvent('show-alert', {
                detail: { type: 'success', message: 'Metadata updated successfully' }
            }));
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
                window.dispatchEvent(new CustomEvent('show-alert', {
                    detail: { type: 'success', message: 'Metadata copied successfully' }
                }));

            } catch (error) {
                console.error(error);
                window.dispatchEvent(new CustomEvent('show-alert', {
                    detail: { type: 'error', message: 'Failed to copy metadata' }
                }));
            }
        },

        // Display Component Helpers
        hasSupplierInfo() {
            return this.metadata.supplier?.name || this.metadata.supplier?.url || this.metadata.supplier?.address;
        },

        getLifecyclePhaseClass(phase: string): string {
            switch (phase) {
                case 'design':
                case 'pre-build':
                    return 'badge-warning';
                case 'build':
                case 'post-build':
                case 'operations':
                    return 'badge-success';
                case 'decommission':
                    return 'badge-danger';
                default:
                    return 'badge-warning';
            }
        },

        formatLifecyclePhase(phase: string): string {
            if (phase === 'pre-build') return 'Pre-Build';
            if (phase === 'post-build') return 'Post-Build';
            return phase.charAt(0).toUpperCase() + phase.slice(1);
        },

        async removeSupplierContact(index: number) {
            if (!this.metadata.supplier?.contacts) return;
            // In the Vue component this was a "TODO: Save changes"
            // so we just update local state for now, assuming edit mode is for saving.
            // But wait, the display component had these X buttons?
            // Yes, "removeSupplierContact" was in display component.
            // It says "TODO: Save changes" in the Vue code.
            // So I will just update local state same as Vue.
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
