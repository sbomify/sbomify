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
 * so a bulk action never reaches a row the person can no longer see. "On
 * screen" is the browser's own visibility check, so a row hidden by a class,
 * the hidden attribute or a hidden ancestor counts as gone too. The rows are
 * re-read when the table changes and again right before a delete is confirmed
 * and posted, which also catches an ancestor outside the table being hidden.
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
    const chosen = new Set(selected);
    const span = shift && anchor !== null ? rowRange(rows, anchor, id) : [id];
    if (!chosen.has(id)) return [...selected, ...span.filter((rowId) => !chosen.has(rowId))];
    const dropped = new Set(span);
    return selected.filter((rowId) => !dropped.has(rowId));
}

/** The selection after the select-all box is clicked: all rows, or none when all were selected. */
export function toggleAllRows(selected: string[], rows: SelectableRow[]): string[] {
    const chosen = new Set(selected);
    const ids = rows.map((row) => row.id);
    if (ids.length > 0 && ids.every((id) => chosen.has(id))) return [];
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

/** Whether `el` is rendered: not display:none itself or under an ancestor that is. */
function isRendered(el: HTMLElement): boolean {
    if (typeof el.checkVisibility === 'function') return el.checkVisibility();
    return el.getClientRects().length > 0;
}

/** The selectable rows inside `root`, in table order. Disabled and hidden rows are left out. */
export function readRows(root: ParentNode): SelectableRow[] {
    return Array.from(root.querySelectorAll<HTMLInputElement>(ROW_INPUT))
        .filter((input) => !input.disabled && isRendered(input))
        .map((input) => ({ id: input.value, label: input.dataset.rowLabel || input.value }));
}

function sameRows(a: SelectableRow[], b: SelectableRow[]): boolean {
    return a.length === b.length && a.every((row, index) => row.id === b[index].id && row.label === b[index].label);
}

/**
 * Whether a mutation can change which rows are selectable. Only the table's
 * head and body hold rows; the bulk bar and the dialog re-render on every
 * selection change and must not set off another read.
 */
function touchesRows(record: MutationRecord): boolean {
    const target = record.target instanceof Element ? record.target : record.target.parentElement;
    return Boolean(target?.closest('table') && !target.closest('[data-bulk-bar], [role="alertdialog"]'));
}

interface SelectionScope {
    rows: SelectableRow[];
    selected: string[];
    chosen: Set<string>;
    confirmingDelete: boolean;
    submitting: boolean;
    $root?: HTMLElement;
    observer: MutationObserver | null;
    pending: number | null;
    refresh(): void;
    setSelected(ids: string[]): void;
}

export function tableSelection() {
    return {
        rows: [] as SelectableRow[],
        selected: [] as string[],
        /** The same ids as `selected`, for constant-time lookups from every row's box. */
        chosen: new Set<string>(),
        anchor: null as string | null,
        confirmingDelete: false,
        /** The delete has been sent and its button is disabled, so it cannot post twice. */
        submitting: false,
        /** An htmx delete is in flight; until it answers, the dialog cannot be dismissed. */
        inFlight: false,
        observer: null as MutationObserver | null,
        pending: null as number | null,

        init(this: SelectionScope): void {
            const root = this.$root;
            if (!root) return;
            this.refresh();
            this.observer = new MutationObserver((records) => {
                if (this.pending !== null || !records.some(touchesRows)) return;
                // One read per frame, however many rows an update touched.
                this.pending = requestAnimationFrame(() => {
                    this.pending = null;
                    this.refresh();
                });
            });
            this.observer.observe(root, {
                childList: true,
                subtree: true,
                attributes: true,
                attributeFilter: ['value', 'disabled', 'style', 'class', 'hidden', 'data-row-label'],
            });
        },

        destroy(this: SelectionScope): void {
            this.observer?.disconnect();
            this.observer = null;
            if (this.pending !== null) cancelAnimationFrame(this.pending);
            this.pending = null;
        },

        setSelected(ids: string[]): void {
            this.selected = ids;
            this.chosen = new Set(ids);
        },

        /**
         * Re-read the rows on screen and drop any selected row that has gone.
         * When the selection changes under an open confirmation, the dialog
         * closes: what it listed is no longer what it would delete.
         */
        refresh(this: SelectionScope): void {
            if (!this.$root) return;
            const rows = readRows(this.$root);
            if (!sameRows(rows, this.rows)) this.rows = rows;
            const kept = pruneSelection(this.selected, rows);
            if (kept.length === this.selected.length) return;
            this.setSelected(kept);
            if (this.confirmingDelete && !this.submitting) this.confirmingDelete = false;
        },

        get count(): number {
            return this.selected.length;
        },

        get allSelected(): boolean {
            return this.rows.length > 0 && this.rows.every((row) => this.chosen.has(row.id));
        },

        get someSelected(): boolean {
            return this.selected.length > 0 && !this.allSelected;
        },

        /** Names of the selected rows, in table order, for the confirmation to list. */
        get selectedLabels(): string[] {
            return this.rows.filter((row) => this.chosen.has(row.id)).map((row) => row.label);
        },

        /** The selection's size with its noun, for the bar and the dialog: "3 components". */
        countOf(noun: string, plural: string): string {
            return countLabel(this.selected.length, noun, plural);
        },

        isSelected(id: string): boolean {
            return this.chosen.has(id);
        },

        toggle(id: string, event?: MouseEvent): void {
            this.setSelected(toggleRow(this.selected, this.rows, id, this.anchor, Boolean(event?.shiftKey)));
            this.anchor = id;
        },

        toggleAll(): void {
            this.setSelected(toggleAllRows(this.selected, this.rows));
            this.anchor = null;
        },

        clear(): void {
            this.setSelected([]);
            this.anchor = null;
        },

        confirmDelete(): void {
            this.refresh();
            if (this.selected.length === 0) return;
            this.submitting = false;
            this.inFlight = false;
            this.confirmingDelete = true;
        },

        cancelDelete(): void {
            if (this.inFlight) return;
            this.confirmingDelete = false;
            this.submitting = false;
        },

        /**
         * The last check before the form posts: re-read the rows, and refuse if
         * the dialog has closed or nothing is left to delete. `htmx` marks the
         * request as in flight, which holds the dialog open until it answers.
         * A plain form post only disables the delete button: the page it
         * navigates to decides what happens next, and if it does not navigate
         * the person can still close the dialog.
         */
        startDelete(htmx = false): boolean {
            this.refresh();
            if (!this.confirmingDelete || this.selected.length === 0 || this.submitting) return false;
            this.submitting = true;
            this.inFlight = htmx;
            return true;
        },

        /** Called when the delete request finishes: success empties the selection, failure keeps it to retry. */
        deleteFinished(successful: boolean): void {
            this.submitting = false;
            this.inFlight = false;
            if (!successful) return;
            this.confirmingDelete = false;
            this.clear();
        },

        /** A page restored from the back/forward cache comes back with the dialog as it was left. */
        pageRestored(event: PageTransitionEvent): void {
            if (!event.persisted) return;
            this.submitting = false;
            this.inFlight = false;
        },
    };
}
