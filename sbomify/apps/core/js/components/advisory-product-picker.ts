export interface PickerRelease {
    id: string;
    label: string;
    created?: string;
}

export interface PickerProduct {
    id: string;
    name: string;
    releases: PickerRelease[];
}

/**
 * Product and version picker for the New Advisory form.
 *
 * An advisory routinely covers a whole product line — several products, or a
 * run of consecutive versions — so ticking one box at a time is the wrong unit
 * of work. This adds the selection idioms a file manager has: shift-click for a
 * range, select-all for the lot, and an all-versions toggle per product.
 *
 * Selection is held here rather than in the checkboxes themselves. Shift-click
 * has to set a range of boxes from one event, which a `x-model` binding cannot
 * express, so the boxes render `:checked` from this state and the form submits
 * from hidden inputs instead. That keeps one source of truth and means a
 * range-select and a plain click go through exactly the same path.
 */
export function advisoryProductPicker(products: PickerProduct[] = [], preselected: unknown = []) {
    return {
        products,
        // Products the caller arrived with already chosen — the products page's
        // row menu links here with the product it was opened from. Coerced,
        // because a template that never sets them serialises an empty string.
        selectedProducts: (Array.isArray(preselected) ? [...preselected] : []) as string[],
        selectedReleases: [] as string[],
        filter: '',

        /**
         * The product whose versions the detail pane is showing.
         *
         * One at a time, rather than many rows expanded in place: a product with
         * a release-per-build has hundreds of versions, and opening it inline
         * pushed every other product off screen. The versions get their own
         * scroll area instead, and the product list stays where it was.
         */
        activeProductId: null as string | null,

        /** Index of the last product row clicked, for shift-click ranges. */
        anchor: null as number | null,
        /** Last release row clicked, keyed by product, for ranges within one product. */
        releaseAnchor: {} as Record<string, number>,

        isProductSelected(id: string): boolean {
            return this.selectedProducts.includes(id);
        },

        isReleaseSelected(id: string): boolean {
            return this.selectedReleases.includes(id);
        },

        isActive(id: string): boolean {
            return this.activeProductId === id;
        },

        /** Open a product in the detail pane, or close it if it is already open. */
        openProduct(id: string): void {
            this.activeProductId = this.activeProductId === id ? null : id;
        },

        get activeProduct(): PickerProduct | null {
            return this.products.find((product) => product.id === this.activeProductId) ?? null;
        },

        /**
         * The versions the detail pane lists.
         *
         * Filtered the same way the list is, so typing a build number narrows
         * the open product to it instead of showing every sibling build.
         */
        get activeReleases(): PickerRelease[] {
            const product = this.activeProduct;
            return product ? this.visibleReleases(product) : [];
        },

        /**
         * Narrow the list by product name or version label.
         *
         * A workspace with a release-per-build has hundreds of versions, and
         * scrolling a box to find one is not a search. Matching on either name
         * or label means typing a build number finds it without first knowing
         * which product shipped it.
         *
         * Both anchors reset, because they hold positions in the list as it was
         * rendered a moment ago; shift-clicking against a stale one selects a
         * range the user cannot see.
         */
        setFilter(value: string): void {
            this.filter = value;
            this.anchor = null;
            this.releaseAnchor = {};
        },

        get filterTerm(): string {
            return this.filter.trim().toLowerCase();
        },

        get visibleProducts(): PickerProduct[] {
            const term = this.filterTerm;
            if (!term) return this.products;
            return this.products.filter(
                (product) =>
                    product.name.toLowerCase().includes(term) ||
                    product.releases.some((release) => release.label.toLowerCase().includes(term)),
            );
        },

        /**
         * A product matched by name keeps all its versions: the user asked for
         * that product, not for a subset of its builds.
         */
        visibleReleases(product: PickerProduct): PickerRelease[] {
            const term = this.filterTerm;
            if (!term || product.name.toLowerCase().includes(term)) return product.releases;
            return product.releases.filter((release) => release.label.toLowerCase().includes(term));
        },

        get allSelected(): boolean {
            return this.products.length > 0 && this.selectedProducts.length === this.products.length;
        },

        get anySelected(): boolean {
            return this.selectedProducts.length > 0;
        },

        /**
         * Select or deselect one product, or a range of them when shift is held.
         *
         * The range takes the state the clicked row ends up in, which is how
         * every file manager behaves: shift-clicking an unticked row after
         * ticking one fills the span in rather than inverting each row.
         */
        toggleProduct(index: number, event?: MouseEvent, visible?: PickerProduct[]): void {
            const list = visible ?? this.products;
            const product = list[index];
            if (!product) return;

            const shouldSelect = !this.isProductSelected(product.id);
            const from = event?.shiftKey && this.anchor !== null ? this.anchor : index;
            const [start, end] = from <= index ? [from, index] : [index, from];

            // As with versions, the range spans the rendered list, so a filter
            // never drags hidden products into the selection.
            for (let i = start; i <= end; i++) {
                this.setProduct(list[i], shouldSelect);
            }
            this.anchor = index;
        },

        setProduct(product: PickerProduct | undefined, selected: boolean): void {
            if (!product) return;

            if (selected) {
                if (!this.isProductSelected(product.id)) {
                    this.selectedProducts = [...this.selectedProducts, product.id];
                }
                return;
            }

            this.selectedProducts = this.selectedProducts.filter((id) => id !== product.id);
            // A version cannot be affected by an advisory that no longer names
            // its product, so dropping the product drops its versions with it.
            const releaseIds = new Set(product.releases.map((release) => release.id));
            this.selectedReleases = this.selectedReleases.filter((id) => !releaseIds.has(id));
        },

        selectAll(): void {
            this.selectedProducts = this.products.map((product) => product.id);
            this.anchor = null;
        },

        clearAll(): void {
            this.selectedProducts = [];
            this.selectedReleases = [];
            this.anchor = null;
        },

        /**
         * Select or deselect one version, or a range within the same product.
         *
         * Ticking a version implies its product: naming an affected version of
         * something you have not marked affected is not a state worth being
         * able to reach.
         */
        toggleRelease(
            product: PickerProduct,
            index: number,
            event?: MouseEvent,
            list: PickerRelease[] = product.releases,
        ): void {
            const release = list[index];
            if (!release) return;

            const shouldSelect = !this.isReleaseSelected(release.id);
            const previous = this.releaseAnchor[product.id];
            const from = event?.shiftKey && previous !== undefined ? previous : index;
            const [start, end] = from <= index ? [from, index] : [index, from];

            // Ranges run over the list as rendered, so shift-clicking under a
            // filter spans what the user can see rather than the rows the
            // filter is hiding between them.
            for (let i = start; i <= end; i++) {
                this.setRelease(list[i], shouldSelect);
            }
            this.releaseAnchor[product.id] = index;

            if (this.selectedReleasesFor(product).length > 0) {
                this.setProduct(product, true);
            }
        },

        setRelease(release: PickerRelease | undefined, selected: boolean): void {
            if (!release) return;

            if (selected) {
                if (!this.isReleaseSelected(release.id)) {
                    this.selectedReleases = [...this.selectedReleases, release.id];
                }
                return;
            }
            this.selectedReleases = this.selectedReleases.filter((id) => id !== release.id);
        },

        selectedReleasesFor(product: PickerProduct): string[] {
            return product.releases.filter((release) => this.isReleaseSelected(release.id)).map((r) => r.id);
        },

        allVersionsSelected(product: PickerProduct, list: PickerRelease[] = product.releases): boolean {
            return list.length > 0 && list.every((release) => this.isReleaseSelected(release.id));
        },

        /**
         * Whether the product's box should render half-ticked.
         *
         * Picking no versions means the advisory covers the product whole, so a
         * full tick is right. Picking every version is the same claim by a
         * longer route, so that is a full tick too. Anything between is a
         * partial claim, and the box should say so rather than implying the
         * whole product is affected.
         */
        isPartiallySelected(product: PickerProduct): boolean {
            if (!this.isProductSelected(product.id)) return false;
            const picked = this.selectedReleasesFor(product).length;
            return picked > 0 && picked < product.releases.length;
        },

        toggleAllVersions(product: PickerProduct, list: PickerRelease[] = product.releases): void {
            const selectAll = !this.allVersionsSelected(product, list);
            list.forEach((release) => this.setRelease(release, selectAll));
            if (selectAll) this.setProduct(product, true);
            this.releaseAnchor[product.id] = 0;
        },

        /**
         * What the collapsed product row says about its versions.
         *
         * No selection means the advisory covers the product as a whole, which
         * is the common case and reads better as "All versions" than as an
         * empty count.
         */
        versionSummary(product: PickerProduct): string {
            if (product.releases.length === 0) return '';
            const count = this.selectedReleasesFor(product).length;
            if (count === 0) return 'All versions';
            return `${count} of ${product.releases.length} versions`;
        },

        /**
         * What the picker has been told, in a sentence.
         *
         * Ticking a product and no versions covers the product whole — every
         * version it has and every version it gets. That is the most common
         * intent and the easiest to reach by accident, and reading it off the
         * checkboxes means knowing that an empty version list is a claim rather
         * than an omission. Saying it in words removes the guess.
         */
        get selectionSummary(): string {
            const chosen = this.products.filter((product) => this.isProductSelected(product.id));
            if (chosen.length === 0) return 'No products selected yet.';

            return chosen
                .map((product) => {
                    const count = this.selectedReleasesFor(product).length;
                    if (count === 0) return `${product.name}: every version, now and in future`;
                    return `${product.name}: ${count} version${count === 1 ? '' : 's'}`;
                })
                .join(' · ');
        },
    };
}
