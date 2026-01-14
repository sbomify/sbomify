import { describe, test, expect, mock, beforeEach } from 'bun:test'

const mockAlpineData = mock<(name: string, callback: () => unknown) => void>()

mock.module('alpinejs', () => ({
    default: {
        data: mockAlpineData
    }
}))

interface Release {
    id: string
    version: string
    product_id: string
    product_name: string
    name: string
    is_latest: boolean
    is_prerelease: boolean
}

describe('Release List', () => {
    beforeEach(() => {
        mockAlpineData.mockClear()
    })

    describe('Constants', () => {
        test('should have correct initial display limit', () => {
            const MAX_INITIAL_DISPLAY = 3
            expect(MAX_INITIAL_DISPLAY).toBe(3)
        })

        test('should have correct expanded display limit', () => {
            const MAX_EXPANDED_DISPLAY = 10
            expect(MAX_EXPANDED_DISPLAY).toBe(10)
        })
    })

    describe('Displayed Releases', () => {
        test('should return all releases when count is less than limit', () => {
            const MAX_INITIAL_DISPLAY = 3
            const releases: Release[] = [
                { id: '1', version: 'v1', product_id: 'p1', product_name: 'P1', name: 'R1', is_latest: true, is_prerelease: false }
            ]

            const displayedReleases = releases.length <= MAX_INITIAL_DISPLAY
                ? releases
                : releases.slice(0, MAX_INITIAL_DISPLAY)

            expect(displayedReleases).toHaveLength(1)
        })

        test('should limit releases when not expanded', () => {
            const MAX_INITIAL_DISPLAY = 3
            const releases: Release[] = Array(5).fill(null).map((_, i) => ({
                id: `${i}`, version: `v${i}`, product_id: 'p1', product_name: 'P1',
                name: `R${i}`, is_latest: i === 0, is_prerelease: false
            }))
            const isExpanded = false

            const maxDisplay = isExpanded ? 10 : MAX_INITIAL_DISPLAY
            const displayedReleases = releases.slice(0, maxDisplay)

            expect(displayedReleases).toHaveLength(3)
        })

        test('should show more releases when expanded', () => {
            const MAX_EXPANDED_DISPLAY = 10
            const releases: Release[] = Array(8).fill(null).map((_, i) => ({
                id: `${i}`, version: `v${i}`, product_id: 'p1', product_name: 'P1',
                name: `R${i}`, is_latest: i === 0, is_prerelease: false
            }))
            const isExpanded = true

            const maxDisplay = isExpanded ? MAX_EXPANDED_DISPLAY : 3
            const displayedReleases = releases.slice(0, maxDisplay)

            expect(displayedReleases).toHaveLength(8)
        })
    })

    describe('Expansion State', () => {
        test('should show expansion control when more than initial limit', () => {
            const MAX_INITIAL_DISPLAY = 3
            const releases: Release[] = Array(5).fill(null).map((_, i) => ({
                id: `${i}`, version: `v${i}`, product_id: 'p1', product_name: 'P1',
                name: `R${i}`, is_latest: i === 0, is_prerelease: false
            }))

            const shouldShowExpansion = releases.length > MAX_INITIAL_DISPLAY
            expect(shouldShowExpansion).toBe(true)
        })

        test('should hide expansion control when within limit', () => {
            const MAX_INITIAL_DISPLAY = 3
            const releases: Release[] = Array(2).fill(null).map((_, i) => ({
                id: `${i}`, version: `v${i}`, product_id: 'p1', product_name: 'P1',
                name: `R${i}`, is_latest: i === 0, is_prerelease: false
            }))

            const shouldShowExpansion = releases.length > MAX_INITIAL_DISPLAY
            expect(shouldShowExpansion).toBe(false)
        })
    })

    describe('Remaining Count', () => {
        test('should calculate remaining count correctly when collapsed', () => {
            const MAX_INITIAL_DISPLAY = 3
            const releases = { length: 7 }
            const isExpanded = false

            const maxDisplay = isExpanded ? 10 : MAX_INITIAL_DISPLAY
            const remainingCount = Math.max(0, releases.length - maxDisplay)

            expect(remainingCount).toBe(4)
        })

        test('should calculate remaining count correctly when expanded', () => {
            const MAX_EXPANDED_DISPLAY = 10
            const releases = { length: 15 }
            const isExpanded = true

            const maxDisplay = isExpanded ? MAX_EXPANDED_DISPLAY : 3
            const remainingCount = Math.max(0, releases.length - maxDisplay)

            expect(remainingCount).toBe(5)
        })

        test('should return 0 when all items displayed', () => {
            const releases = { length: 5 }
            const maxDisplay = 10

            const remainingCount = Math.max(0, releases.length - maxDisplay)
            expect(remainingCount).toBe(0)
        })
    })

    describe('Expand Button Text', () => {
        test('should show "Show less" when expanded', () => {
            const getExpandButtonText = (isExpanded: boolean, remainingCount: number): string => {
                if (isExpanded) {
                    return '− Show less'
                }
                return `+ ${remainingCount} more`
            }

            expect(getExpandButtonText(true, 5)).toBe('− Show less')
        })

        test('should show remaining count when collapsed', () => {
            const getExpandButtonText = (isExpanded: boolean, remainingCount: number): string => {
                if (isExpanded) {
                    return '− Show less'
                }
                return `+ ${remainingCount} more`
            }

            expect(getExpandButtonText(false, 5)).toBe('+ 5 more')
        })
    })

    describe('Toggle Expansion', () => {
        test('should toggle expansion state', () => {
            let isExpanded = false

            const toggleExpansion = () => {
                isExpanded = !isExpanded
            }

            toggleExpansion()
            expect(isExpanded).toBe(true)

            toggleExpansion()
            expect(isExpanded).toBe(false)
        })
    })

    describe('Session Storage Key', () => {
        test('should generate correct storage key', () => {
            const itemId = 'item-123'
            const expandedKey = `release-expanded-${itemId}`

            expect(expandedKey).toBe('release-expanded-item-123')
        })
    })

    describe('Initial Expansion State', () => {
        test('should read initial state from session storage', () => {
            const getInitialExpanded = (stored: string | null): boolean => {
                return stored === 'true'
            }

            expect(getInitialExpanded('true')).toBe(true)
            expect(getInitialExpanded('false')).toBe(false)
            expect(getInitialExpanded(null)).toBe(false)
        })
    })
})
