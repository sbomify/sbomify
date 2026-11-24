import type { AlpineComponent } from 'alpinejs';

interface InventoryRequest {
    elt?: HTMLElement;
    target?: HTMLElement;
    xhr?: XMLHttpRequest;
    successful?: boolean;
}

interface InventoryHeading {
    heading: string;
    subtitle: string;
    title: string;
}

interface InventoryTabs {
    selectedKind: string;
    loadedKind: string;
    heading: string;
    headingSubtitle: string;
    headings: Record<string, InventoryHeading>;
    applyHeading(kind: string, retitle: boolean): void;
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
        heading: '',
        headingSubtitle: '',
        headings: {},
        loading: false,
        showSkeleton: false,
        loadingTimer: undefined,
        failed: false,
        request: null,

        init() {
            // The tabs carry the words each kind gives the page, so a switch can
            // retitle the page from what is already in the document.
            this.$el.querySelectorAll<HTMLElement>('[data-inventory-tab]').forEach((tab) => {
                const kind = tab.dataset.inventoryTab;
                if (!kind) return;
                this.headings[kind] = {
                    heading: tab.dataset.inventoryHeading || '',
                    subtitle: tab.dataset.inventorySubtitle || '',
                    title: tab.dataset.inventoryTitle || '',
                };
            });
            // History may restore a later panel inside the original frame.
            this.loadedKind = this.$el.querySelector<HTMLElement>('#inventory-panel')?.dataset.inventoryKind || 'products';
            this.selectedKind = this.loadedKind;
            // On a fresh page this restates the words the server already
            // rendered. On Back it corrects them: HTMX snapshots the title when
            // it leaves a page, by which point the tab being opened has already
            // retitled it, so the restored panel can arrive under the wrong one.
            this.applyHeading(this.loadedKind, true);
        },

        applyHeading(kind, retitle) {
            const words = this.headings[kind];
            if (!words) return;
            this.heading = words.heading;
            this.headingSubtitle = words.subtitle;
            if (retitle && words.title) document.title = words.title;
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
            this.applyHeading(kind, true);
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
            this.applyHeading(this.loadedKind, true);
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
            this.applyHeading(this.loadedKind, true);
            this.clearLoading();
            this.failed = false;
            this.request = null;
        },
    };
}
