import type { AlpineComponent } from 'alpinejs';

interface InventoryRequest {
    elt?: HTMLElement;
    target?: HTMLElement;
    xhr?: XMLHttpRequest;
    successful?: boolean;
}

interface InventoryTabs {
    selectedKind: string;
    loadedKind: string;
    loading: boolean;
    showSkeleton: boolean;
    loadingTimer: ReturnType<typeof setTimeout> | undefined;
    clearLoading(): void;
    failed: boolean;
    request: XMLHttpRequest | null;
    confirm(event: CustomEvent<InventoryRequest>): void;
    begin(event: CustomEvent<InventoryRequest>): void;
    finish(event: CustomEvent<InventoryRequest>): void;
    swapped(event: CustomEvent<InventoryRequest>): void;
}

/** The navigation stays mounted while HTMX replaces only the selected panel. */
export function inventoryTabs(): AlpineComponent<InventoryTabs> {
    return {
        selectedKind: 'products',
        loadedKind: 'products',
        loading: false,
        showSkeleton: false,
        loadingTimer: undefined,
        failed: false,
        request: null,

        init() {
            // History may restore a later panel inside the original frame.
            this.loadedKind = this.$el.querySelector<HTMLElement>('#inventory-panel')?.dataset.inventoryKind || 'products';
            this.selectedKind = this.loadedKind;
        },

        confirm(event) {
            // A background refresh must not replace a tab the user just chose.
            if (this.loading && event.detail.elt === this.$el) event.preventDefault();
        },

        begin(event) {
            const { elt, target, xhr } = event.detail;
            if (target?.id !== 'inventory-panel' || !xhr) return;
            const kind = elt?.dataset.inventoryTab;
            if (!kind) return;
            this.request = xhr;
            this.selectedKind = kind;
            this.failed = false;
            this.loading = true;
            clearTimeout(this.loadingTimer);
            // Fast responses replace the previous panel without flashing a skeleton.
            this.loadingTimer = setTimeout(() => {
                this.showSkeleton = true;
                this.loadingTimer = undefined;
            }, 200);
        },

        clearLoading() {
            clearTimeout(this.loadingTimer);
            this.loadingTimer = undefined;
            this.loading = false;
            this.showSkeleton = false;
        },

        destroy() {
            this.clearLoading();
        },

        finish(event) {
            if (event.detail.xhr !== this.request) return;
            // A successful panel swap already cleared request in swapped().
            // If it is still pending, even a 204 delivered no usable panel.
            this.selectedKind = this.loadedKind;
            this.clearLoading();
            this.failed = true;
            this.request = null;
        },

        swapped(event) {
            if (event.detail.target?.id !== 'inventory-panel') return;
            if (this.request && event.detail.xhr !== this.request) return;
            const panel = this.$el.querySelector<HTMLElement>('#inventory-panel');
            if (!panel?.dataset.inventoryKind) return;
            this.loadedKind = panel.dataset.inventoryKind;
            this.selectedKind = this.loadedKind;
            this.clearLoading();
            this.failed = false;
            this.request = null;
        },
    };
}
