/**
 * Row selection for a c-tables.shell, and the bulk actions that act on it.
 *
 * The rows are read from the DOM rather than handed in, so a server-rendered
 * table, an HTMX swap and an Alpine `x-for` all select the same way: each row's
 * c-tables.select-cell renders an `input[data-row-select]` carrying the row's
 * id as its value and its name as `data-row-label`.
 *
 * Only rows on screen count. A row filtered out by a search, hidden by the
 * pager or swapped out by HTMX leaves the selection when it leaves the screen,
 * so a bulk action never reaches a row the person can no longer see.
 */

import { formatNumber } from '../number-format';

export interface SelectableRow {
    id: string;
    label: string;
}

/** Ids of `rows` from `from` to `to` inclusive, in table order, whichever comes first. */
export function rowRange(rows: SelectableRow[], from: string, to: string): string[] {
    const start = rows.findIndex((row) => row.id === from);
    const end = rows.findIndex((row) => row.id === to);
    if (start === -1 || end === -1) return [to];
    const [low, high] = start <= end ? [start, end] : [end, start];
    return rows.slice(low, high + 1).map((row) => row.id);
}

/**
 * The selection after clicking row `id`.
 *
 * A plain click toggles the one row. A shift-click after an earlier click sets
 * every row between the two to the state the clicked row is moving to, which is
 * how a run of rows is picked without clicking each.
 */
export function toggleRow(
    selected: string[],
    rows: SelectableRow[],
    id: string,
    anchor: string | null,
    shift: boolean,
): string[] {
    const selecting = !selected.includes(id);
    const span = shift && anchor !== null ? rowRange(rows, anchor, id) : [id];
    if (selecting) return [...selected, ...span.filter((rowId) => !selected.includes(rowId))];
    return selected.filter((rowId) => !span.includes(rowId));
}

/** The selection after the select-all box is clicked: all rows, or none when all were selected. */
export function toggleAllRows(selected: string[], rows: SelectableRow[]): string[] {
    const ids = rows.map((row) => row.id);
    if (ids.length > 0 && ids.every((id) => selected.includes(id))) return [];
    return ids;
}

/** `selected` without the ids that are no longer among `rows`, in selection order. */
export function pruneSelection(selected: string[], rows: SelectableRow[]): string[] {
    const ids = new Set(rows.map((row) => row.id));
    return selected.filter((id) => ids.has(id));
}

/** A count with its noun: "1 component", "3 components". */
export function countLabel(count: number, noun: string, plural: string): string {
    return `${formatNumber(count)} ${count === 1 ? noun : plural}`;
}

const ROW_INPUT = 'input[data-row-select]';

/** The selectable rows inside `root`, in table order. Disabled and hidden rows are left out. */
export function readRows(root: ParentNode): SelectableRow[] {
    return Array.from(root.querySelectorAll<HTMLInputElement>(ROW_INPUT))
        .filter((input) => !input.disabled && input.closest('tr')?.style.display !== 'none')
        .map((input) => ({ id: input.value, label: input.dataset.rowLabel || input.value }));
}

function sameRows(a: SelectableRow[], b: SelectableRow[]): boolean {
    return a.length === b.length && a.every((row, index) => row.id === b[index].id && row.label === b[index].label);
}

interface SelectionScope {
    rows: SelectableRow[];
    selected: string[];
    $root?: HTMLElement;
    refresh(): void;
}

export function tableSelection() {
    return {
        rows: [] as SelectableRow[],
        selected: [] as string[],
        anchor: null as string | null,
        confirmingDelete: false,
        submitting: false,

        init(this: SelectionScope): void {
            const root = this.$root;
            if (!root) return;
            this.refresh();
            new MutationObserver(() => this.refresh()).observe(root, {
                childList: true,
                subtree: true,
                attributes: true,
                attributeFilter: ['value', 'disabled', 'style', 'data-row-label'],
            });
        },

        /** Re-read the rows on screen and drop any selected row that has gone. */
        refresh(this: SelectionScope): void {
            if (!this.$root) return;
            const rows = readRows(this.$root);
            if (!sameRows(rows, this.rows)) this.rows = rows;
            const kept = pruneSelection(this.selected, rows);
            if (kept.length !== this.selected.length) this.selected = kept;
        },

        get count(): number {
            return this.selected.length;
        },

        get allSelected(): boolean {
            return this.rows.length > 0 && this.rows.every((row) => this.selected.includes(row.id));
        },

        get someSelected(): boolean {
            return this.selected.length > 0 && !this.allSelected;
        },

        /** Names of the selected rows, in table order, for the confirmation to list. */
        get selectedLabels(): string[] {
            return this.rows.filter((row) => this.selected.includes(row.id)).map((row) => row.label);
        },

        /** The selection's size with its noun, for the bar and the dialog: "3 components". */
        countOf(noun: string, plural: string): string {
            return countLabel(this.selected.length, noun, plural);
        },

        isSelected(id: string): boolean {
            return this.selected.includes(id);
        },

        toggle(id: string, event?: MouseEvent): void {
            this.selected = toggleRow(this.selected, this.rows, id, this.anchor, Boolean(event?.shiftKey));
            this.anchor = id;
        },

        toggleAll(): void {
            this.selected = toggleAllRows(this.selected, this.rows);
            this.anchor = null;
        },

        clear(): void {
            this.selected = [];
            this.anchor = null;
        },

        confirmDelete(): void {
            if (this.selected.length > 0) this.confirmingDelete = true;
        },

        cancelDelete(): void {
            if (this.submitting) return;
            this.confirmingDelete = false;
        },

        /** Called when the delete request finishes: success empties the selection, failure keeps it to retry. */
        deleteFinished(successful: boolean): void {
            this.submitting = false;
            if (!successful) return;
            this.confirmingDelete = false;
            this.clear();
        },
    };
}
