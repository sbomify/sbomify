/** Keep a server-sorted table at the reader's position when HTMX replaces it. */
interface TablePosition {
    index: number;
    label: string | null;
    left: number;
    top: number;
    focusedColumn: string | null;
}

function viewports(root: HTMLElement): HTMLElement[] {
    return root.matches('[data-table-viewport]')
        ? [root]
        : Array.from(root.querySelectorAll<HTMLElement>('[data-table-viewport]'));
}

export function initTableSorting(): void {
    const pending = new WeakMap<XMLHttpRequest, TablePosition>();

    document.body.addEventListener('htmx:beforeSwap', ((event: CustomEvent) => {
        const source = event.detail.requestConfig?.elt;
        const target = event.detail.target;
        if (!(source instanceof HTMLElement) || !(target instanceof HTMLElement) || !event.detail.shouldSwap) return;
        const control = source.closest<HTMLElement>('[data-table-sort]');
        const viewport = control?.closest<HTMLElement>('[data-table-viewport]');
        if (!viewport || !control || !target.contains(viewport)) return;

        pending.set(event.detail.xhr, {
            index: viewports(target).indexOf(viewport),
            label: viewport.querySelector('table')?.getAttribute('aria-label') ?? null,
            left: viewport.scrollLeft,
            top: viewport.scrollTop,
            focusedColumn: document.activeElement === control ? control.dataset.tableSort ?? null : null,
        });
    }) as EventListener);

    document.body.addEventListener('htmx:afterSwap', ((event: CustomEvent) => {
        const position = pending.get(event.detail.xhr);
        // The event is dispatched on the replacement; detail.target can be the
        // detached original when the swap uses outerHTML.
        if (!position || !(event.target instanceof HTMLElement)) return;
        const viewport = viewports(event.target)[position.index];
        if (!viewport || viewport.querySelector('table')?.getAttribute('aria-label') !== position.label) return;
        // A sidebar's out-of-band swap can arrive before the table for this request.
        pending.delete(event.detail.xhr);

        if (position.focusedColumn !== null) {
            const control = Array.from(viewport.querySelectorAll<HTMLElement>('[data-table-sort]'))
                .find(element => element.dataset.tableSort === position.focusedColumn);
            control?.focus({ preventScroll: true });
        }
        viewport.scrollLeft = position.left;
        viewport.scrollTop = position.top;
    }) as EventListener);
}
