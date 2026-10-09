/**
 * Column labels for tables that stack on phones.
 *
 * Below the sm breakpoint a `table[data-stack]` lays each row out as a block
 * (tailwind.src.css, "Stacked tables"), so the header row is no longer beside
 * the values it names. Each cell takes its column's header text as
 * `data-label`, which the stylesheet prints above the value.
 *
 * Tables arrive three ways: in the page, swapped in by HTMX, and filled by
 * Alpine `x-for` after either. The first two are caught on load and after each
 * settle; the third by watching each table for new rows.
 */

const TABLE = 'table[data-stack]';
const observed = new WeakSet<HTMLTableElement>();

function headerLabels(table: HTMLTableElement): string[] {
    const labels: string[] = [];
    // The row that holds the header cells: a stray empty <tr> before it would
    // otherwise leave every cell unlabelled.
    const headerRow = Array.from(table.tHead?.rows ?? []).find((row) => row.cells.length > 0);
    if (!headerRow) return labels;
    for (const th of Array.from(headerRow.cells)) {
        // An explicit data-label wins, for a header whose text is not a label.
        const text = (th.dataset.label ?? th.textContent ?? '').replace(/\s+/g, ' ').trim();
        for (let span = 0; span < Math.max(th.colSpan, 1); span++) labels.push(text);
    }
    return labels;
}

export function labelTable(table: HTMLTableElement): void {
    const labels = headerLabels(table);
    if (!labels.length) return;
    for (const body of Array.from(table.tBodies)) {
        for (const row of Array.from(body.rows)) {
            let column = 0;
            for (const cell of Array.from(row.cells)) {
                const label = cell.colSpan > 1 ? '' : labels[column] ?? '';
                // A cell's own label is the author's choice; only fill the gap.
                if (!cell.hasAttribute('data-label') && label) cell.setAttribute('data-label', label);
                column += Math.max(cell.colSpan, 1);
            }
        }
    }
}

function scan(root: ParentNode): void {
    if (typeof root.querySelectorAll !== 'function') return;
    root.querySelectorAll<HTMLTableElement>(TABLE).forEach((table) => {
        labelTable(table);
        if (observed.has(table)) return;
        observed.add(table);
        new MutationObserver(() => labelTable(table)).observe(table, { childList: true, subtree: true });
    });
}

export function initTableStack(): void {
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => scan(document));
    } else {
        scan(document);
    }
    // The whole document, not the event's element: after an outerHTML swap
    // that element is the one just removed, and the new table is not under it.
    document.addEventListener('htmx:afterSettle', () => scan(document));
}

// Guarded so the pure labelling can be imported by a spec without a DOM.
if (typeof document !== 'undefined' && typeof document.querySelectorAll === 'function') initTableStack();
