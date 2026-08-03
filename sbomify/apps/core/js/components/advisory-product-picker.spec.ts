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

describe('expanding rows', () => {
    test('expansion is independent of selection', () => {
        picker.toggleExpanded('p1')
        expect(picker.isExpanded('p1')).toBe(true)
        expect(picker.isProductSelected('p1')).toBe(false)

        picker.toggleExpanded('p1')
        expect(picker.isExpanded('p1')).toBe(false)
    })
})
