import { describe, test, expect, beforeEach } from 'bun:test'
import { advisoryProductPicker, type PickerProduct } from './advisory-product-picker'

const PRODUCTS: PickerProduct[] = [
    { id: 'p1', name: 'Gateway', releases: [{ id: 'r1', label: '1.0' }, { id: 'r2', label: '1.1' }, { id: 'r3', label: '1.2' }] },
    { id: 'p2', name: 'Vault', releases: [{ id: 'r4', label: '2.0' }] },
    { id: 'p3', name: 'Edge', releases: [] },
    { id: 'p4', name: 'Console', releases: [] },
]

const shift = { shiftKey: true } as MouseEvent
const plain = { shiftKey: false } as MouseEvent

let picker: ReturnType<typeof advisoryProductPicker>

beforeEach(() => {
    picker = advisoryProductPicker(structuredClone(PRODUCTS))
})

describe('selecting products', () => {
    test('a plain click toggles one product', () => {
        picker.toggleProduct(0, plain)
        expect(picker.selectedProducts).toEqual(['p1'])

        picker.toggleProduct(0, plain)
        expect(picker.selectedProducts).toEqual([])
    })

    test('shift-click fills the range between the anchor and the click', () => {
        picker.toggleProduct(0, plain)
        picker.toggleProduct(2, shift)
        expect(picker.selectedProducts).toEqual(['p1', 'p2', 'p3'])
    })

    test('a shift range works backwards too', () => {
        picker.toggleProduct(3, plain)
        picker.toggleProduct(1, shift)
        expect(picker.selectedProducts.sort()).toEqual(['p2', 'p3', 'p4'])
    })

    test('shift-clicking a selected row clears the range rather than inverting each one', () => {
        picker.selectAll()
        picker.toggleProduct(0, plain)   // p1 off; anchor here
        picker.toggleProduct(2, shift)   // clears p1..p3, leaves p4
        expect(picker.selectedProducts).toEqual(['p4'])
    })

    test('shift with no anchor behaves like a plain click', () => {
        picker.toggleProduct(2, shift)
        expect(picker.selectedProducts).toEqual(['p3'])
    })

    test('select all and clear all', () => {
        picker.selectAll()
        expect(picker.allSelected).toBe(true)
        expect(picker.selectedProducts).toHaveLength(4)

        picker.clearAll()
        expect(picker.allSelected).toBe(false)
        expect(picker.anySelected).toBe(false)
    })
})

describe('arriving with a product already chosen', () => {
    test('a preselected product is ticked, covering every version', () => {
        const opened = advisoryProductPicker(structuredClone(PRODUCTS), ['p2'])

        expect(opened.selectedProducts).toEqual(['p2'])
        expect(opened.selectionSummary).toBe('Vault: every version, now and in future')
    })

    test('it can still be cleared like any other selection', () => {
        const opened = advisoryProductPicker(structuredClone(PRODUCTS), ['p1'])
        opened.toggleProduct(0, plain)

        expect(opened.selectedProducts).toEqual([])
    })

    test('nothing preselected is the normal empty start', () => {
        expect(advisoryProductPicker(structuredClone(PRODUCTS)).selectedProducts).toEqual([])
    })

    test('a template that never set the ids serialises an empty string, not a list', () => {
        expect(advisoryProductPicker(structuredClone(PRODUCTS), '').selectedProducts).toEqual([])
    })

    test('the caller\'s list is copied, not adopted', () => {
        const ids = ['p1']
        const opened = advisoryProductPicker(structuredClone(PRODUCTS), ids)
        opened.toggleProduct(1, plain)

        expect(ids).toEqual(['p1'])
    })
})

describe('selecting versions', () => {
    test('ticking a version implies its product', () => {
        picker.toggleRelease(picker.products[0], 1, plain)
        expect(picker.selectedReleases).toEqual(['r2'])
        expect(picker.isProductSelected('p1')).toBe(true)
    })

    test('shift-click fills a range of versions within one product', () => {
        picker.toggleRelease(picker.products[0], 0, plain)
        picker.toggleRelease(picker.products[0], 2, shift)
        expect(picker.selectedReleases).toEqual(['r1', 'r2', 'r3'])
    })

    test('deselecting a product drops the versions selected under it', () => {
        picker.toggleRelease(picker.products[0], 0, plain)
        picker.toggleRelease(picker.products[1], 0, plain)
        expect(picker.selectedReleases.sort()).toEqual(['r1', 'r4'])

        picker.toggleProduct(0, plain)   // Gateway off
        expect(picker.selectedReleases).toEqual(['r4'])
        expect(picker.isProductSelected('p1')).toBe(false)
    })

    test('the all-versions toggle selects then clears every version', () => {
        const gateway = picker.products[0]
        picker.toggleAllVersions(gateway)
        expect(picker.allVersionsSelected(gateway)).toBe(true)
        expect(picker.isProductSelected('p1')).toBe(true)

        picker.toggleAllVersions(gateway)
        expect(picker.allVersionsSelected(gateway)).toBe(false)
        expect(picker.selectedReleases).toEqual([])
    })

    test('a version range anchors per product, not globally', () => {
        picker.toggleRelease(picker.products[0], 0, plain)   // anchor in Gateway
        picker.toggleRelease(picker.products[1], 0, shift)   // Vault has its own anchor
        expect(picker.selectedReleases.sort()).toEqual(['r1', 'r4'])
    })
})

describe('the collapsed row summary', () => {
    test('no versions picked means the whole product is affected', () => {
        expect(picker.versionSummary(picker.products[0])).toBe('All versions')
    })

    test('some versions picked shows the count', () => {
        picker.toggleRelease(picker.products[0], 0, plain)
        expect(picker.versionSummary(picker.products[0])).toBe('1 of 3 versions')
    })

    test('a product with no releases says nothing about versions', () => {
        expect(picker.versionSummary(picker.products[2])).toBe('')
    })
})

describe('opening a product in the detail pane', () => {
    test('opening is independent of selection', () => {
        picker.openProduct('p1')
        expect(picker.isActive('p1')).toBe(true)
        expect(picker.isProductSelected('p1')).toBe(false)

        picker.openProduct('p1')
        expect(picker.isActive('p1')).toBe(false)
    })

    test('only one product is open at a time', () => {
        picker.openProduct('p1')
        picker.openProduct('p2')

        expect(picker.isActive('p2')).toBe(true)
        expect(picker.isActive('p1')).toBe(false)
    })

    test('the open product exposes its own versions', () => {
        picker.openProduct('p1')

        expect(picker.activeProduct?.id).toBe('p1')
        expect(picker.activeReleases.map((release) => release.id)).toEqual(
            picker.products[0]!.releases.map((release) => release.id),
        )
    })

    test('nothing open means no versions to show', () => {
        expect(picker.activeProduct).toBeNull()
        expect(picker.activeReleases).toEqual([])
    })

    test('the open product narrows to the filter, like the list does', () => {
        const [target] = picker.products[0]!.releases
        picker.openProduct('p1')
        picker.setFilter(target!.label)

        expect(picker.activeReleases.map((release) => release.id)).toEqual([target!.id])
    })
})

describe('the half-ticked parent box', () => {
    test('an unselected product is never partial', () => {
        expect(picker.isPartiallySelected(picker.products[0])).toBe(false)
    })

    test('a product selected with no versions picked is fully ticked, not partial', () => {
        picker.toggleProduct(0, plain)
        expect(picker.isProductSelected('p1')).toBe(true)
        // No versions picked means the whole product is covered.
        expect(picker.isPartiallySelected(picker.products[0])).toBe(false)
    })

    test('some but not all versions picked shows partial', () => {
        picker.toggleRelease(picker.products[0], 0, plain)
        expect(picker.isPartiallySelected(picker.products[0])).toBe(true)
    })

    test('every version picked is the whole product again, so not partial', () => {
        picker.toggleAllVersions(picker.products[0])
        expect(picker.allVersionsSelected(picker.products[0])).toBe(true)
        expect(picker.isPartiallySelected(picker.products[0])).toBe(false)
    })

    test('a product with no versions can never be partial', () => {
        picker.toggleProduct(2, plain)
        expect(picker.isPartiallySelected(picker.products[2])).toBe(false)
    })
})

describe('filtering', () => {
    test('a product name match keeps all of that product\'s versions', () => {
        picker.setFilter('gateway')
        expect(picker.visibleProducts.map((p) => p.id)).toEqual(['p1'])
        expect(picker.visibleReleases(picker.products[0]).length).toBe(3)
    })

    test('a version label match narrows to that version, and finds the product by it', () => {
        picker.setFilter('1.2')
        expect(picker.visibleProducts.map((p) => p.id)).toEqual(['p1'])
        expect(picker.visibleReleases(picker.products[0]).map((r) => r.id)).toEqual(['r3'])
    })

    test('nothing matching leaves an empty list rather than the full one', () => {
        picker.setFilter('nonesuch')
        expect(picker.visibleProducts).toEqual([])
    })

    test('a click under a filter selects the row shown, not the one at that index unfiltered', () => {
        picker.setFilter('vault')
        picker.toggleProduct(0, plain, picker.visibleProducts)
        expect(picker.selectedProducts).toEqual(['p2'])
    })

    test('a version click under a filter selects the version shown', () => {
        picker.setFilter('1.2')
        const product = picker.products[0]
        picker.toggleRelease(product, 0, plain, picker.visibleReleases(product))
        expect(picker.selectedReleases).toEqual(['r3'])
    })

    test('a shift range under a filter never reaches a hidden row', () => {
        picker.setFilter('1.')
        const product = picker.products[0]
        const visible = picker.visibleReleases(product)
        picker.toggleRelease(product, 0, plain, visible)
        picker.toggleRelease(product, 1, shift, visible)
        expect(picker.selectedReleases.sort()).toEqual(['r1', 'r2'])
    })

    test('changing the filter drops the anchors, so the next shift-click starts fresh', () => {
        picker.toggleProduct(0, plain)
        expect(picker.anchor).toBe(0)
        picker.setFilter('vault')
        expect(picker.anchor).toBe(null)
        expect(picker.releaseAnchor).toEqual({})
    })

    test('select-every-version under a filter takes only the visible ones', () => {
        picker.setFilter('1.2')
        const product = picker.products[0]
        picker.toggleAllVersions(product, picker.visibleReleases(product))
        expect(picker.selectedReleases).toEqual(['r3'])
    })
})

describe('selection summary', () => {
    test('says so when nothing is picked', () => {
        expect(picker.selectionSummary).toBe('No products selected yet.')
    })

    test('a bare product tick reads as covering every version, now and later', () => {
        picker.toggleProduct(0, plain)
        expect(picker.selectionSummary).toBe('Gateway: every version, now and in future')
    })

    test('picked versions are counted, and singular reads singular', () => {
        picker.toggleRelease(picker.products[0], 0, plain)
        expect(picker.selectionSummary).toBe('Gateway: 1 version')
    })

    test('several products are joined', () => {
        picker.toggleProduct(0, plain)
        picker.toggleProduct(1, plain)
        expect(picker.selectionSummary).toBe(
            'Gateway: every version, now and in future · Vault: every version, now and in future',
        )
    })
})
