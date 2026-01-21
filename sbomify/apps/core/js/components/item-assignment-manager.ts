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

export function registerItemAssignmentManager() {
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

        init() {
            this.loadData();
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
            if (!this.assignedSearch) return this.assignedItems;
            const search = this.assignedSearch.toLowerCase();
            return this.assignedItems.filter((item: AssignableItem) =>
                item.name.toLowerCase().includes(search) ||
                (item.description && item.description.toLowerCase().includes(search))
            );
        },

        get filteredAvailable(): AssignableItem[] {
            if (!this.availableSearch) return this.availableItems;
            const search = this.availableSearch.toLowerCase();
            return this.availableItems.filter((item: AssignableItem) =>
                item.name.toLowerCase().includes(search) ||
                (item.description && item.description.toLowerCase().includes(search))
            );
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
