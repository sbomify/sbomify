import type { AlpineComponent } from 'alpinejs';

interface ScrollableTabs {
    overflow: boolean;
    canScrollBack: boolean;
    canScrollForward: boolean;
    resizeObserver: ResizeObserver | undefined;
    selectionObserver: MutationObserver | undefined;
    initTimer: ReturnType<typeof setTimeout> | undefined;
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
            this.resizeObserver = new ResizeObserver(() => {
                this.measure();
                this.revealActive();
            });
            this.resizeObserver.observe(this.$root);
            this.resizeObserver.observe(this.$refs.scroller);
            this.resizeObserver.observe(this.$refs.tabItems);
            this.selectionObserver = new MutationObserver(() => this.revealActive());
            this.selectionObserver.observe(this.$refs.tabItems, {
                subtree: true, attributes: true, attributeFilter: ['aria-current', 'aria-selected']
            });
            this.initTimer = setTimeout(() => {
                this.measure();
                this.revealActive();
            });
        },

        measure() {
            const row = this.$refs.scroller;
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
            const row = this.$refs.scroller;
            if (!(target instanceof HTMLElement) || !row.contains(target)) return;
            const bounds = row.getBoundingClientRect();
            const tab = target.getBoundingClientRect();
            if (tab.width > bounds.width || tab.left < bounds.left) row.scrollLeft += tab.left - bounds.left;
            else if (tab.right > bounds.right) row.scrollLeft += tab.right - bounds.right;
            this.measure();
        },

        revealActive() {
            this.reveal(this.$refs.tabItems.querySelector('[aria-current="page"], [aria-selected="true"]'));
        },

        destroy() {
            clearTimeout(this.initTimer);
            this.resizeObserver?.disconnect();
            this.selectionObserver?.disconnect();
        }
    };
}
