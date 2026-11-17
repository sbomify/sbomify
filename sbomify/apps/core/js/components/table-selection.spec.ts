import { describe, test, expect, beforeEach } from 'bun:test'
import {
    readRows,
    countLabel,
    pruneSelection,
    rowRange,
    tableSelection,
    toggleAllRows,
    toggleRow,
    type SelectableRow,
} from './table-selection'

const ROWS: SelectableRow[] = [
    { id: 'a', label: 'acme-gateway-core' },
    { id: 'b', label: 'acme-vault-core' },
    { id: 'c', label: 'acme-billing-service' },
    { id: 'd', label: 'acme-audit-log' },
]

describe('rowRange', () => {
    test('runs between two rows in table order, whichever was clicked first', () => {
        expect(rowRange(ROWS, 'b', 'd')).toEqual(['b', 'c', 'd'])
        expect(rowRange(ROWS, 'd', 'b')).toEqual(['b', 'c', 'd'])
    })

    test('falls back to the clicked row when the anchor has left the table', () => {
        expect(rowRange(ROWS, 'gone', 'c')).toEqual(['c'])
    })
})

describe('toggleRow', () => {
    test('a plain click toggles one row', () => {
        expect(toggleRow([], ROWS, 'b', null, false)).toEqual(['b'])
        expect(toggleRow(['b'], ROWS, 'b', 'b', false)).toEqual([])
    })

    test('shift-click selects the run since the anchor', () => {
        expect(toggleRow(['a'], ROWS, 'c', 'a', true)).toEqual(['a', 'b', 'c'])
    })

    test('shift-click on a selected row clears the run', () => {
        expect(toggleRow(['a', 'b', 'c', 'd'], ROWS, 'c', 'a', true)).toEqual(['d'])
    })

    test('shift-click with no anchor is a plain click', () => {
        expect(toggleRow([], ROWS, 'c', null, true)).toEqual(['c'])
    })
})

describe('toggleAllRows', () => {
    test('selects every row, then clears them all', () => {
        expect(toggleAllRows(['b'], ROWS)).toEqual(['a', 'b', 'c', 'd'])
        expect(toggleAllRows(['a', 'b', 'c', 'd'], ROWS)).toEqual([])
    })

    test('selects nothing in an empty table', () => {
        expect(toggleAllRows([], [])).toEqual([])
    })
})

describe('pruneSelection', () => {
    test('drops rows no longer on screen and keeps the rest in order', () => {
        expect(pruneSelection(['d', 'x', 'a'], ROWS)).toEqual(['d', 'a'])
    })
})

describe('countLabel', () => {
    test('agrees with its count', () => {
        expect(countLabel(1, 'component', 'components')).toBe('1 component')
        expect(countLabel(3, 'component', 'components')).toBe('3 components')
        expect(countLabel(0, 'component', 'components')).toBe('0 components')
    })
})

describe('tableSelection', () => {
    let selection: ReturnType<typeof tableSelection>

    beforeEach(() => {
        selection = tableSelection()
        selection.rows = structuredClone(ROWS)
    })

    test('isSelected agrees with the selection after every kind of change', () => {
        selection.toggle('b')
        expect(selection.isSelected('b')).toBe(true)
        selection.toggleAll()
        expect(ROWS.every((row) => selection.isSelected(row.id))).toBe(true)
        selection.clear()
        expect(selection.isSelected('b')).toBe(false)
    })

    test('select-all is checked only when every row is, and indeterminate in between', () => {
        expect(selection.allSelected).toBe(false)
        expect(selection.someSelected).toBe(false)

        selection.toggle('a')
        expect(selection.someSelected).toBe(true)
        expect(selection.allSelected).toBe(false)

        selection.toggleAll()
        expect(selection.allSelected).toBe(true)
        expect(selection.someSelected).toBe(false)
        expect(selection.count).toBe(4)
    })

    test('select-all is never checked in an empty table', () => {
        selection.rows = []
        expect(selection.allSelected).toBe(false)
    })

    test('the shift key on the click event selects a run', () => {
        selection.toggle('a')
        selection.toggle('c', { shiftKey: true } as MouseEvent)
        expect(selection.selected).toEqual(['a', 'b', 'c'])
    })

    test('labels come back in table order, not click order', () => {
        selection.toggle('c')
        selection.toggle('a')
        expect(selection.selectedLabels).toEqual(['acme-gateway-core', 'acme-billing-service'])
        expect(selection.countOf('component', 'components')).toBe('2 components')
    })

    test('the dialog only opens with something selected', () => {
        selection.confirmDelete()
        expect(selection.confirmingDelete).toBe(false)

        selection.toggle('a')
        selection.confirmDelete()
        expect(selection.confirmingDelete).toBe(true)
    })

    test('an htmx delete in flight holds the dialog open', () => {
        selection.toggle('a')
        selection.confirmDelete()
        expect(selection.startDelete(true)).toBe(true)
        selection.cancelDelete()
        expect(selection.confirmingDelete).toBe(true)
    })

    test('a plain form post can still be dismissed if the page does not navigate', () => {
        selection.toggle('a')
        selection.confirmDelete()
        expect(selection.startDelete()).toBe(true)
        expect(selection.submitting).toBe(true)
        selection.cancelDelete()
        expect(selection.confirmingDelete).toBe(false)
        expect(selection.submitting).toBe(false)
    })

    test('the delete cannot be sent twice', () => {
        selection.toggle('a')
        selection.confirmDelete()
        expect(selection.startDelete(true)).toBe(true)
        expect(selection.startDelete(true)).toBe(false)
    })

    test('nothing posts once the dialog has closed', () => {
        selection.toggle('a')
        expect(selection.startDelete()).toBe(false)
    })

    test('a page restored from the back/forward cache unlocks the dialog', () => {
        selection.toggle('a')
        selection.confirmDelete()
        selection.startDelete(true)
        selection.pageRestored({ persisted: true } as PageTransitionEvent)
        expect(selection.submitting).toBe(false)
        expect(selection.inFlight).toBe(false)
    })

    test('a failed delete keeps the dialog and the selection to retry', () => {
        selection.toggle('a')
        selection.confirmDelete()
        selection.startDelete(true)
        selection.deleteFinished(false)
        expect(selection.submitting).toBe(false)
        expect(selection.confirmingDelete).toBe(true)
        expect(selection.selected).toEqual(['a'])
    })

    test('a successful delete closes the dialog and clears the selection', () => {
        selection.toggle('a')
        selection.confirmDelete()
        selection.startDelete(true)
        selection.deleteFinished(true)
        expect(selection.confirmingDelete).toBe(false)
        expect(selection.selected).toEqual([])
    })
})

interface FakeInput {
    value: string
    disabled: boolean
    dataset: { rowLabel?: string }
    checkVisibility(): boolean
}

function fakeRoot(inputs: FakeInput[]): ParentNode {
    return { querySelectorAll: () => inputs } as unknown as ParentNode
}

function input(value: string, { visible = true, disabled = false } = {}): FakeInput {
    return { value, disabled, dataset: { rowLabel: `name-${value}` }, checkVisibility: () => visible }
}

describe('readRows', () => {
    test('leaves out disabled rows and rows the browser does not render', () => {
        const rows = readRows(fakeRoot([input('a'), input('b', { visible: false }), input('c', { disabled: true })]))
        expect(rows).toEqual([{ id: 'a', label: 'name-a' }])
    })
})

describe('a selection that changes under the dialog', () => {
    test('closes the dialog instead of posting a set it did not list', () => {
        const visible = { a: true, b: true }
        const inputs = [input('a'), input('b')]
        inputs[1].checkVisibility = () => visible.b
        const selection = tableSelection() as ReturnType<typeof tableSelection> & { $root: HTMLElement }
        selection.$root = fakeRoot(inputs) as unknown as HTMLElement
        selection.refresh()
        selection.toggleAll()
        selection.confirmDelete()
        expect(selection.confirmingDelete).toBe(true)

        visible.b = false
        expect(selection.startDelete()).toBe(false)
        expect(selection.confirmingDelete).toBe(false)
        expect(selection.selected).toEqual(['a'])
    })
})
