import Alpine from 'alpinejs';
import $axios from '../utils';
import { showError, showSuccess } from '../alerts';

interface AssignableItem {
    id: string;
    name: string;
    description?: string;
    is_public?: boolean;
    visibility?: string;
    [key: string]: unknown;
}

interface ItemAssignmentManagerParams {
    parentType: 'product' | 'project';
    parentId: string;
    childType: 'project' | 'component';
    assignedItems?: AssignableItem[];
    availableItems?: AssignableItem[];
}

export function registerItemAssignmentManager(): void {
    Alpine.data('itemAssignmentManager', ({
        parentType,
        parentId,
        childType,
        assignedItems = [],
        availableItems = []
    }: ItemAssignmentManagerParams) => ({
        isLoading: false,
        isUpdating: false,
        assignedItems: assignedItems as AssignableItem[],
        availableItems: availableItems as AssignableItem[],
        assignedSearch: '',
        availableSearch: '',
        parentType,
        parentId,
        childType,
        draggedItem: null as AssignableItem | null,
        dragSource: '' as 'assigned' | 'available' | '',

        _wsHandler: null as EventListener | null,
        _debounceTimer: null as ReturnType<typeof setTimeout> | null,

        init() {
            this.loadData();

            // Listen for WebSocket events to refresh data
            const relevantEvents = this.childType === 'component'
                ? ['component_created', 'component_deleted']
                : ['project_created', 'project_deleted'];

            this._wsHandler = ((event: CustomEvent) => {
                if (relevantEvents.includes(event.detail?.type)) {
                    // Debounce loadData to avoid redundant API calls when multiple events arrive
                    if (this._debounceTimer) {
                        clearTimeout(this._debounceTimer);
                    }
                    this._debounceTimer = setTimeout(() => {
                        this.loadData();
                        this._debounceTimer = null;
                    }, 300);
                }
            }) as EventListener;

            window.addEventListener('ws:message', this._wsHandler);
        },

        destroy() {
            // Clean up WebSocket event listener and debounce timer
            if (this._wsHandler) {
                window.removeEventListener('ws:message', this._wsHandler);
                this._wsHandler = null;
            }
            if (this._debounceTimer) {
                clearTimeout(this._debounceTimer);
                this._debounceTimer = null;
            }
        },

        async loadData() {
            this.isLoading = true;
            try {
                const parentEndpoint = `/api/v1/${this.parentType}s/${this.parentId}`;
                const availableEndpoint = `/api/v1/${this.childType}s`;

                const [parentRes, availableRes] = await Promise.all([
                    $axios.get(parentEndpoint),
                    $axios.get(availableEndpoint)
                ]);

                // Extract assigned items from parent response
                const assignedKey = this.parentType === 'product' ? 'projects' : 'components';
                this.assignedItems = parentRes.data[assignedKey] || [];

                // Filter out assigned items from available list
                const allItems = availableRes.data.items || availableRes.data.results || availableRes.data;
                const assignedIds = new Set(this.assignedItems.map((item: AssignableItem) => item.id));
                this.availableItems = allItems.filter((item: AssignableItem) => !assignedIds.has(item.id));
            } catch (error) {
                console.error('Failed to load data:', error);
                showError('Failed to load items');
            } finally {
                this.isLoading = false;
            }
        },

        get filteredAssigned(): AssignableItem[] {
            const items = this.assignedSearch
                ? this.assignedItems.filter((item: AssignableItem) =>
                    item.name.toLowerCase().includes(this.assignedSearch.toLowerCase()) ||
                    (item.description && item.description.toLowerCase().includes(this.assignedSearch.toLowerCase()))
                )
                : this.assignedItems;
            return [...items].sort((a, b) => a.name.localeCompare(b.name));
        },

        get filteredAvailable(): AssignableItem[] {
            const items = this.availableSearch
                ? this.availableItems.filter((item: AssignableItem) =>
                    item.name.toLowerCase().includes(this.availableSearch.toLowerCase()) ||
                    (item.description && item.description.toLowerCase().includes(this.availableSearch.toLowerCase()))
                )
                : this.availableItems;
            return [...items].sort((a, b) => a.name.localeCompare(b.name));
        },

        async addItem(item: AssignableItem) {
            if (this.isUpdating) return;
            this.isUpdating = true;
            try {
                const childIds = [...this.assignedItems.map((i: AssignableItem) => i.id), item.id];
                await $axios.patch(`/api/v1/${this.parentType}s/${this.parentId}`, {
                    [`${this.childType}_ids`]: childIds
                });

                this.assignedItems.push(item);
                this.availableItems = this.availableItems.filter((i: AssignableItem) => i.id !== item.id);
                showSuccess(`${this.childType.charAt(0).toUpperCase() + this.childType.slice(1)} added successfully`);
            } catch (error) {
                console.error('Failed to add item:', error);
                showError('Failed to add item');
            } finally {
                this.isUpdating = false;
            }
        },

        async removeItem(item: AssignableItem) {
            if (this.isUpdating) return;
            this.isUpdating = true;
            try {
                const childIds = this.assignedItems
                    .filter((i: AssignableItem) => i.id !== item.id)
                    .map((i: AssignableItem) => i.id);

                await $axios.patch(`/api/v1/${this.parentType}s/${this.parentId}`, {
                    [`${this.childType}_ids`]: childIds
                });

                this.assignedItems = this.assignedItems.filter((i: AssignableItem) => i.id !== item.id);
                this.availableItems.push(item);
                showSuccess(`${this.childType.charAt(0).toUpperCase() + this.childType.slice(1)} removed successfully`);
            } catch (error) {
                console.error('Failed to remove item:', error);
                showError('Failed to remove item');
            } finally {
                this.isUpdating = false;
            }
        },

        onDragStart(event: DragEvent, item: AssignableItem, source: 'assigned' | 'available') {
            this.draggedItem = item;
            this.dragSource = source;
            if (event.dataTransfer) {
                event.dataTransfer.effectAllowed = 'move';
                event.dataTransfer.setData('text/plain', item.id);
            }
        },

        onDragOver(event: DragEvent) {
            event.preventDefault();
            if (event.dataTransfer) {
                event.dataTransfer.dropEffect = 'move';
            }
        },

        onDrop(event: DragEvent, target: 'assigned' | 'available') {
            event.preventDefault();
            if (!this.draggedItem || this.dragSource === target) return;

            if (target === 'assigned') {
                this.addItem(this.draggedItem);
            } else {
                this.removeItem(this.draggedItem);
            }

            this.draggedItem = null;
            this.dragSource = '';
        },

        onDragEnd() {
            this.draggedItem = null;
            this.dragSource = '';
        }
    }));
}
