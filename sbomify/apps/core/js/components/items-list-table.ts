import Alpine from 'alpinejs';
import $axios from '../utils';
import { showError } from '../alerts';
import { createPaginationData } from './pagination-controls';

interface ListItem {
    id: string;
    name: string;
    description?: string;
    created_at?: string;
    updated_at?: string;
    [key: string]: unknown;
}

interface PaginationMeta {
    total_items: number;
    page_size: number;
    current_page: number;
    total_pages: number;
}

interface ItemsListTableParams {
    itemType: 'products' | 'projects' | 'components';
    workspaceId?: string;
    initialItems?: ListItem[];
    initialPagination?: PaginationMeta;
    canCreate?: boolean;
    canEdit?: boolean;
    canDelete?: boolean;
}

interface ItemsListTableData {
    items: ListItem[];
    isLoading: boolean;
    itemType: 'products' | 'projects' | 'components';
    workspaceId: string;
    canCreate: boolean;
    canEdit: boolean;
    canDelete: boolean;
    currentPage: number;
    totalItems: number;
    pageSize: number;
    pageSizeOptions: number[];
    ellipsis: string;
    totalPages: number;
    startItem: number;
    endItem: number;
    visiblePages: (number | string)[];
    init(): void;
    handlePaginationChange(): void;
    loadItems(): Promise<void>;
    getItemUrl(item: ListItem): string;
    getAddUrl(): string;
    formatDate(dateString?: string): string;
    getTypeIcon(): string;
    getTypeSingular(): string;
    isVisible(index: number): boolean;
    goToPage(page: number): void;
    handlePageSizeChange(event: Event): void;
}

export function registerItemsListTable(): void {
    Alpine.data('itemsListTable', ({
        itemType,
        workspaceId = '',
        initialItems = [],
        initialPagination,
        canCreate = true,
        canEdit = true,
        canDelete = true
    }: ItemsListTableParams) => {
        const paginationData = createPaginationData(
            initialPagination?.total_items || 0,
            [10, 15, 25, 50, 100],
            initialPagination?.current_page || 1
        );

        return {
            items: initialItems as ListItem[],
            isLoading: false,
            itemType,
            workspaceId,
            canCreate,
            canEdit,
            canDelete,
            ...paginationData,

            init() {
                if (initialItems.length === 0) {
                    this.loadItems();
                }

                // Listen for refresh events based on item type
                if (window.eventBus && window.EVENTS) {
                    let eventName: string | undefined;
                    if (itemType === 'products') {
                        eventName = window.EVENTS.REFRESH_PRODUCTS;
                    } else if (itemType === 'projects') {
                        eventName = window.EVENTS.REFRESH_PROJECTS;
                    } else if (itemType === 'components') {
                        eventName = window.EVENTS.REFRESH_COMPONENTS;
                    }
                    
                    if (eventName) {
                        window.eventBus.on(eventName, () => {
                            this.loadItems();
                        });
                    }
                }

                // Watch for pagination changes - using x-effect in template instead
                // Effect logic: x-effect="currentPage, pageSize; handlePaginationChange()"
            },

            handlePaginationChange(this: ItemsListTableData): void {
                if (this.pageSize) {
                    this.currentPage = 1;
                }
                this.loadItems();
            },

            async loadItems() {
                this.isLoading = true;
                try {
                    const params = new URLSearchParams({
                        page: this.currentPage.toString(),
                        page_size: this.pageSize.toString()
                    });

                    if (this.workspaceId) {
                        params.append('workspace', this.workspaceId);
                    }

                    const response = await $axios.get(`/api/v1/${this.itemType}/?${params.toString()}`);
                    this.items = response.data.results || response.data;
                    this.totalItems = response.data.count || this.items.length;
                } catch (error) {
                    console.error('Failed to load items:', error);
                    showError('Failed to load items');
                } finally {
                    this.isLoading = false;
                }
            },

            getItemUrl(item: ListItem): string {
                return `/${this.itemType}/${item.id}/`;
            },

            getAddUrl(): string {
                return `/${this.itemType}/add/`;
            },

            formatDate(dateString?: string): string {
                if (!dateString) return '-';
                const date = new Date(dateString);
                return date.toLocaleDateString('en-US', {
                    year: 'numeric',
                    month: 'short',
                    day: 'numeric'
                });
            },

            getTypeIcon(): string {
                switch (this.itemType) {
                    case 'products':
                        return 'fas fa-box';
                    case 'projects':
                        return 'fas fa-project-diagram';
                    case 'components':
                        return 'fas fa-cube';
                    default:
                        return 'fas fa-folder';
                }
            },

            getTypeSingular(): string {
                return this.itemType.slice(0, -1);
            }
        };
    });
}
