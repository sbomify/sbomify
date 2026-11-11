import type { AlpineComponent } from 'alpinejs';

interface ScrollableTabs {
    overflow: boolean;
    canScrollBack: boolean;
    canScrollForward: boolean;
    resizeObserver: ResizeObserver | undefined;
    selectionObserver: MutationObserver | undefined;
    initTimer: ReturnType<typeof setTimeout> | undefined;
    rows(): { scroller: HTMLElement; tabItems: HTMLElement } | null;
    observe(retry: boolean): void;
    measure(): void;
    scroll(direction: number): void;
    reveal(target: EventTarget | null): void;
    revealActive(): void;
}

/** Tabs keep native scrolling. Arrows move only this row, never the page. */
export function scrollableTabs(): AlpineComponent<ScrollableTabs> {
    return {
        overflow: false,
        canScrollBack: false,
        canScrollForward: false,
        resizeObserver: undefined as ResizeObserver | undefined,
        selectionObserver: undefined as MutationObserver | undefined,
        initTimer: undefined as ReturnType<typeof setTimeout> | undefined,

        init() {
            this.observe(true);
        },

        /** The row's elements, or null while a morph has not put them in place. */
        rows() {
            const { scroller, tabItems } = this.$refs;
            if (!(scroller instanceof HTMLElement) || !(tabItems instanceof HTMLElement)) return null;
            return { scroller, tabItems };
        },

        observe(retry: boolean) {
            const rows = this.rows();
            if (!rows) {
                if (retry) this.$nextTick(() => this.observe(false));
                return;
            }
            this.resizeObserver = new ResizeObserver(() => {
                this.measure();
                this.revealActive();
            });
            this.resizeObserver.observe(this.$root);
            this.resizeObserver.observe(rows.scroller);
            this.resizeObserver.observe(rows.tabItems);
            this.selectionObserver = new MutationObserver(() => this.revealActive());
            this.selectionObserver.observe(rows.tabItems, {
                subtree: true, attributes: true, attributeFilter: ['aria-current', 'aria-selected']
            });
            this.initTimer = setTimeout(() => {
                this.measure();
                this.revealActive();
            });
        },

        measure() {
            const row = this.rows()?.scroller;
            if (!row) return;
            this.overflow = row.scrollWidth > this.$root.clientWidth + 1;
            this.canScrollBack = row.scrollLeft > 1;
            this.canScrollForward = row.scrollLeft + row.clientWidth < row.scrollWidth - 1;
        },

        scroll(direction: number) {
            const row = this.$refs.scroller;
            row.scrollBy({
                left: direction * row.clientWidth * 0.75,
                behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth'
            });
        },

        reveal(target: EventTarget | null) {
            const row = this.rows()?.scroller;
            if (!row || !(target instanceof HTMLElement) || !row.contains(target)) return;
            const bounds = row.getBoundingClientRect();
            const tab = target.getBoundingClientRect();
            if (tab.width > bounds.width || tab.left < bounds.left) row.scrollLeft += tab.left - bounds.left;
            else if (tab.right > bounds.right) row.scrollLeft += tab.right - bounds.right;
            this.measure();
        },

        revealActive() {
            this.reveal(this.rows()?.tabItems.querySelector('[aria-current="page"], [aria-selected="true"]') ?? null);
        },

        destroy() {
            clearTimeout(this.initTimer);
            this.resizeObserver?.disconnect();
            this.selectionObserver?.disconnect();
        }
    };
}
