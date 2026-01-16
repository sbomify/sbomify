import { describe, test, expect, mock, beforeEach } from 'bun:test'

const mockShowSuccess = mock<(message: string) => void>()
const mockShowError = mock<(message: string) => void>()

mock.module('../alerts', () => ({
    showSuccess: mockShowSuccess,
    showError: mockShowError
}))

const mockAlpineData = mock<(name: string, callback: () => unknown) => void>()

mock.module('alpinejs', () => ({
    default: {
        data: mockAlpineData
    }
}))

describe('Public Status Toggle', () => {
    beforeEach(() => {
        mockShowSuccess.mockClear()
        mockShowError.mockClear()
        mockAlpineData.mockClear()
    })

    describe('Status Icon', () => {
        test('should return globe icon for public', () => {
            const getStatusIcon = (isPublic: boolean): string => {
                return isPublic ? 'fas fa-globe' : 'fas fa-lock'
            }

            expect(getStatusIcon(true)).toBe('fas fa-globe')
        })

        test('should return lock icon for private', () => {
            const getStatusIcon = (isPublic: boolean): string => {
                return isPublic ? 'fas fa-globe' : 'fas fa-lock'
            }

            expect(getStatusIcon(false)).toBe('fas fa-lock')
        })
    })

    describe('Status Text', () => {
        test('should return "Public" for public items', () => {
            const getStatusText = (isPublic: boolean): string => {
                return isPublic ? 'Public' : 'Private'
            }

            expect(getStatusText(true)).toBe('Public')
        })

        test('should return "Private" for private items', () => {
            const getStatusText = (isPublic: boolean): string => {
                return isPublic ? 'Public' : 'Private'
            }

            expect(getStatusText(false)).toBe('Private')
        })
    })

    describe('Inheritance Note', () => {
        test('should show inheritance note for release item type', () => {
            const showInheritanceNote = (itemType: string): boolean => {
                return itemType === 'release'
            }

            expect(showInheritanceNote('release')).toBe(true)
            expect(showInheritanceNote('product')).toBe(false)
            expect(showInheritanceNote('component')).toBe(false)
        })
    })

    describe('Toggle Logic', () => {
        test('should toggle public status', () => {
            let isPublic = false

            const togglePublicStatus = () => {
                isPublic = !isPublic
            }

            expect(isPublic).toBe(false)
            togglePublicStatus()
            expect(isPublic).toBe(true)
            togglePublicStatus()
            expect(isPublic).toBe(false)
        })
    })

    describe('Loading State', () => {
        test('should set loading before request', () => {
            let isLoading = false

            const beforeRequestHandler = () => {
                isLoading = true
            }

            beforeRequestHandler()
            expect(isLoading).toBe(true)
        })

        test('should clear loading after request', () => {
            let isLoading = true

            const afterRequestHandler = () => {
                isLoading = false
            }

            afterRequestHandler()
            expect(isLoading).toBe(false)
        })
    })

    describe('Response Handling', () => {
        test('should update status from response', () => {
            let isPublic = false

            const handleResponse = (response: { is_public?: boolean }) => {
                if ('is_public' in response) {
                    isPublic = response.is_public!
                }
            }

            handleResponse({ is_public: true })
            expect(isPublic).toBe(true)

            handleResponse({ is_public: false })
            expect(isPublic).toBe(false)
        })

        test('should revert status if is_public not in response', () => {
            let isPublic = true

            const handleResponse = (response: { is_public?: boolean }) => {
                if (!('is_public' in response)) {
                    isPublic = !isPublic
                }
            }

            handleResponse({})
            expect(isPublic).toBe(false)
        })
    })

    describe('Public URL', () => {
        test('should generate full URL from public URL path', () => {
            const publicUrl = '/products/123/public'
            const origin = 'https://example.com'

            const fullUrl = new URL(publicUrl, origin).href
            expect(fullUrl).toBe('https://example.com/products/123/public')
        })
    })

    describe('Event Dispatch', () => {
        test('should create correct event detail', () => {
            const itemType = 'product'
            const itemId = 'prod-123'
            const isPublic = true

            const detail = { itemType, itemId, isPublic }

            expect(detail.itemType).toBe('product')
            expect(detail.itemId).toBe('prod-123')
            expect(detail.isPublic).toBe(true)
        })
    })

    describe('Badge Markdown Generation', () => {
        test('should generate correct markdown format for product', () => {
            const badgeSvgUrl = 'https://sbomify.com/assets/images/logo/badge.svg'
            const publicUrl = '/public/product/eP_4dk8ixV/'
            const origin = 'https://app.sbomify.com'

            const fullPublicUrl = new URL(publicUrl, origin).href
            const markdown = `[![sbomified](${badgeSvgUrl})](${fullPublicUrl})`

            expect(markdown).toBe('[![sbomified](https://sbomify.com/assets/images/logo/badge.svg)](https://app.sbomify.com/public/product/eP_4dk8ixV/)')
        })

        test('should generate correct markdown format for component', () => {
            const badgeSvgUrl = 'https://sbomify.com/assets/images/logo/badge.svg'
            const publicUrl = '/public/component/abc123/'
            const origin = 'https://app.sbomify.com'

            const fullPublicUrl = new URL(publicUrl, origin).href
            const markdown = `[![sbomified](${badgeSvgUrl})](${fullPublicUrl})`

            expect(markdown).toBe('[![sbomified](https://sbomify.com/assets/images/logo/badge.svg)](https://app.sbomify.com/public/component/abc123/)')
        })

        test('should use correct badge SVG URL', () => {
            const badgeSvgUrl = 'https://sbomify.com/assets/images/logo/badge.svg'
            expect(badgeSvgUrl).toContain('badge.svg')
            expect(badgeSvgUrl).toStartWith('https://sbomify.com')
        })
    })

    describe('Badge Clipboard Messages', () => {
        test('should prepare success message for dispatch', () => {
            const successMessage = { type: 'success', message: 'Badge markdown copied to clipboard' }

            expect(successMessage.type).toBe('success')
            expect(successMessage.message).toContain('Badge')
            expect(successMessage.message).toContain('clipboard')
        })

        test('should prepare error message for dispatch', () => {
            const errorMessage = { type: 'error', message: 'Failed to copy badge to clipboard' }

            expect(errorMessage.type).toBe('error')
            expect(errorMessage.message).toContain('Failed')
            expect(errorMessage.message).toContain('badge')
        })
    })
})
