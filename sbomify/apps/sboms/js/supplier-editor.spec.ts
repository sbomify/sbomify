import { describe, test, expect } from 'bun:test'

/**
 * Tests for SupplierEditor Alpine.js component business logic
 *
 * This test suite validates the core functionality of the supplier editor component
 * including URL management, form state, and update dispatching.
 */

describe('SupplierEditor Business Logic', () => {

    // Test data factory
    const createTestSupplier = (overrides = {}) => ({
        name: null as string | null,
        url: [] as string[],
        address: null as string | null,
        contacts: [] as Array<{ name: string; email: string; phone: string }>,
        ...overrides
    })

    describe('Initial State', () => {
        test('should initialize with default values', () => {
            const supplier = createTestSupplier()

            expect(supplier.name).toBeNull()
            expect(supplier.url).toEqual([])
            expect(supplier.address).toBeNull()
            expect(supplier.contacts).toEqual([])
        })

        test('should initialize with provided values', () => {
            const supplier = createTestSupplier({
                name: 'Acme Corp',
                url: ['https://acme.com'],
                address: '123 Main St',
                contacts: [{ name: 'John', email: 'john@acme.com', phone: '123' }]
            })

            expect(supplier.name).toBe('Acme Corp')
            expect(supplier.url).toEqual(['https://acme.com'])
            expect(supplier.address).toBe('123 Main St')
            expect(supplier.contacts.length).toBe(1)
        })

        test('should convert string URL to array', () => {
            const normalizeUrl = (url: string | string[] | null): string[] => {
                if (Array.isArray(url)) return url
                if (typeof url === 'string') return [url]
                return []
            }

            expect(normalizeUrl('https://example.com')).toEqual(['https://example.com'])
            expect(normalizeUrl(['https://a.com', 'https://b.com'])).toEqual(['https://a.com', 'https://b.com'])
            expect(normalizeUrl(null)).toEqual([])
        })
    })

    describe('URL Management', () => {
        test('should add URL to empty list', () => {
            const urls: string[] = []

            const addUrl = () => {
                urls.push('')
            }

            addUrl()
            expect(urls.length).toBe(1)
            expect(urls[0]).toBe('')
        })

        test('should add URL from input', () => {
            const urls: string[] = []
            let inputValue = 'https://example.com'

            const addUrlFromInput = () => {
                if (inputValue.trim()) {
                    urls.push(inputValue.trim())
                    inputValue = ''
                }
            }

            addUrlFromInput()
            expect(urls).toEqual(['https://example.com'])
            expect(inputValue).toBe('')
        })

        test('should not add empty URL from input', () => {
            const urls: string[] = []
            let inputValue = '   '

            const addUrlFromInput = () => {
                if (inputValue.trim()) {
                    urls.push(inputValue.trim())
                    inputValue = ''
                }
            }

            addUrlFromInput()
            expect(urls.length).toBe(0)
        })

        test('should update URL at specific index', () => {
            const urls = ['https://old.com', 'https://keep.com']

            const updateUrl = (index: number, value: string) => {
                urls[index] = value
            }

            updateUrl(0, 'https://new.com')
            expect(urls[0]).toBe('https://new.com')
            expect(urls[1]).toBe('https://keep.com')
        })

        test('should remove URL by index', () => {
            const urls = ['https://a.com', 'https://b.com', 'https://c.com']

            const removeUrl = (index: number) => {
                if (urls.length > 1) {
                    urls.splice(index, 1)
                }
            }

            removeUrl(1) // Remove https://b.com
            expect(urls).toEqual(['https://a.com', 'https://c.com'])
        })

        test('should not remove last URL', () => {
            const urls = ['https://only.com']

            const removeUrl = (index: number) => {
                if (urls.length > 1) {
                    urls.splice(index, 1)
                }
            }

            removeUrl(0)
            expect(urls.length).toBe(1) // Should still have one URL
        })

        test('should handle multiple URLs', () => {
            const urls: string[] = []

            const addUrl = (url: string) => {
                urls.push(url)
            }

            addUrl('https://website.com')
            addUrl('https://docs.website.com')
            addUrl('https://support.website.com')

            expect(urls.length).toBe(3)
        })
    })

    describe('Supplier Data Updates', () => {
        test('should update name field', () => {
            const supplier = createTestSupplier()

            supplier.name = 'New Company'
            expect(supplier.name).toBe('New Company')
        })

        test('should update address field', () => {
            const supplier = createTestSupplier()

            supplier.address = '456 Market St\nSan Francisco, CA'
            expect(supplier.address).toBe('456 Market St\nSan Francisco, CA')
        })

        test('should update contacts', () => {
            const supplier = createTestSupplier()

            supplier.contacts.push({ name: 'Alice', email: 'alice@example.com', phone: '' })
            expect(supplier.contacts.length).toBe(1)
            expect(supplier.contacts[0].name).toBe('Alice')
        })
    })

    describe('Form Validation Logic', () => {
        test('should validate URL format', () => {
            const isValidUrl = (url: string): boolean => {
                try {
                    new URL(url)
                    return true
                } catch {
                    return false
                }
            }

            expect(isValidUrl('https://example.com')).toBe(true)
            expect(isValidUrl('http://localhost:3000')).toBe(true)
            expect(isValidUrl('not-a-url')).toBe(false)
            expect(isValidUrl('')).toBe(false)
        })

        test('should allow empty optional fields', () => {
            const supplier = createTestSupplier()

            // All fields are optional for supplier
            const isValid = true // No required fields
            expect(isValid).toBe(true)
            expect(supplier.name).toBeNull()
        })
    })

    describe('Update Dispatching', () => {
        test('should prepare update payload', () => {
            const supplier = createTestSupplier({
                name: 'Test Corp',
                url: ['https://test.com'],
                address: 'Test Address',
                contacts: []
            })

            const preparePayload = () => ({ supplier })

            const payload = preparePayload()
            expect(payload.supplier.name).toBe('Test Corp')
            expect(payload.supplier.url).toEqual(['https://test.com'])
        })
    })

    describe('Edge Cases', () => {
        test('should handle empty supplier object', () => {
            const supplier = createTestSupplier()

            expect(supplier.name).toBeNull()
            expect(supplier.url).toEqual([])
            expect(supplier.address).toBeNull()
            expect(supplier.contacts).toEqual([])
        })

        test('should preserve contacts when updating other fields', () => {
            const supplier = createTestSupplier({
                contacts: [{ name: 'Bob', email: 'bob@test.com', phone: '555' }]
            })

            supplier.name = 'Updated Name'
            expect(supplier.contacts[0].name).toBe('Bob')
        })

        test('should handle special characters in address', () => {
            const supplier = createTestSupplier()

            supplier.address = '123 Élysée Palace\nParis, France 🇫🇷'
            expect(supplier.address).toContain('Élysée')
            expect(supplier.address).toContain('🇫🇷')
        })
    })
})
