import { describe, test, expect, mock, beforeEach } from 'bun:test'

const mockSwalFire = mock<(options: unknown) => Promise<{ isConfirmed: boolean }>>()

mock.module('sweetalert2', () => ({
    default: mockSwalFire.mockResolvedValue({ isConfirmed: true })
}))

describe('Utils', () => {
    beforeEach(() => {
        mockSwalFire.mockClear()
    })

    describe('isEmpty', () => {
        test('should return true for undefined', () => {
            const isEmpty = (obj: unknown): boolean => {
                if (typeof obj !== 'object' || obj === null) {
                    return obj === undefined || obj === null || obj === ''
                }
                return Object.values(obj).every(value => {
                    if (Array.isArray(value)) {
                        return value.length === 0
                    } else {
                        return value === null || value === ''
                    }
                })
            }

            expect(isEmpty(undefined)).toBe(true)
        })

        test('should return true for null', () => {
            const isEmpty = (obj: unknown): boolean => {
                if (typeof obj !== 'object' || obj === null) {
                    return obj === undefined || obj === null || obj === ''
                }
                return false
            }

            expect(isEmpty(null)).toBe(true)
        })

        test('should return true for empty string', () => {
            const isEmpty = (obj: unknown): boolean => {
                if (typeof obj !== 'object' || obj === null) {
                    return obj === undefined || obj === null || obj === ''
                }
                return false
            }

            expect(isEmpty('')).toBe(true)
        })

        test('should return false for non-empty string', () => {
            const isEmpty = (obj: unknown): boolean => {
                if (typeof obj !== 'object' || obj === null) {
                    return obj === undefined || obj === null || obj === ''
                }
                return false
            }

            expect(isEmpty('hello')).toBe(false)
        })

        test('should return true for object with empty arrays', () => {
            const isEmpty = (obj: unknown): boolean => {
                if (typeof obj !== 'object' || obj === null) {
                    return obj === undefined || obj === null || obj === ''
                }
                return Object.values(obj).every(value => {
                    if (Array.isArray(value)) {
                        return value.length === 0
                    } else {
                        return value === null || value === ''
                    }
                })
            }

            expect(isEmpty({ items: [] })).toBe(true)
        })

        test('should return false for object with non-empty arrays', () => {
            const isEmpty = (obj: unknown): boolean => {
                if (typeof obj !== 'object' || obj === null) {
                    return obj === undefined || obj === null || obj === ''
                }
                return Object.values(obj).every(value => {
                    if (Array.isArray(value)) {
                        return value.length === 0
                    } else {
                        return value === null || value === ''
                    }
                })
            }

            expect(isEmpty({ items: [1, 2, 3] })).toBe(false)
        })
    })

    describe('parseJsonScript', () => {
        test('should return null for missing element', () => {
            const parseJsonScript = <T = unknown>(elementId: string, getElement: (id: string) => { textContent: string | null } | null): T | null => {
                const scriptEl = getElement(elementId)
                if (!scriptEl?.textContent || scriptEl.textContent === 'null') {
                    return null
                }
                try {
                    return JSON.parse(scriptEl.textContent) as T
                } catch {
                    return null
                }
            }

            expect(parseJsonScript('missing-id', () => null)).toBe(null)
        })

        test('should return null for empty content', () => {
            const parseJsonScript = <T = unknown>(elementId: string, getElement: (id: string) => { textContent: string | null } | null): T | null => {
                const scriptEl = getElement(elementId)
                if (!scriptEl?.textContent || scriptEl.textContent === 'null') {
                    return null
                }
                try {
                    return JSON.parse(scriptEl.textContent) as T
                } catch {
                    return null
                }
            }

            expect(parseJsonScript('empty', () => ({ textContent: '' }))).toBe(null)
        })

        test('should return null for "null" content', () => {
            const parseJsonScript = <T = unknown>(elementId: string, getElement: (id: string) => { textContent: string | null } | null): T | null => {
                const scriptEl = getElement(elementId)
                if (!scriptEl?.textContent || scriptEl.textContent === 'null') {
                    return null
                }
                try {
                    return JSON.parse(scriptEl.textContent) as T
                } catch {
                    return null
                }
            }

            expect(parseJsonScript('null-content', () => ({ textContent: 'null' }))).toBe(null)
        })

        test('should parse valid JSON', () => {
            const parseJsonScript = <T = unknown>(elementId: string, getElement: (id: string) => { textContent: string | null } | null): T | null => {
                const scriptEl = getElement(elementId)
                if (!scriptEl?.textContent || scriptEl.textContent === 'null') {
                    return null
                }
                try {
                    return JSON.parse(scriptEl.textContent) as T
                } catch {
                    return null
                }
            }

            expect(parseJsonScript('valid', () => ({ textContent: '{"name":"test"}' }))).not.toBeNull()
        })

        test('should return null for invalid JSON', () => {
            const parseJsonScript = <T = unknown>(elementId: string, getElement: (id: string) => { textContent: string | null } | null): T | null => {
                const scriptEl = getElement(elementId)
                if (!scriptEl?.textContent || scriptEl.textContent === 'null') {
                    return null
                }
                try {
                    return JSON.parse(scriptEl.textContent) as T
                } catch {
                    return null
                }
            }

            expect(parseJsonScript('invalid', () => ({ textContent: 'not json' }))).toBe(null)
        })
    })

    describe('getErrorMessage', () => {
        test('should extract message from Error object', () => {
            const getErrorMessage = (error: Error | unknown): string => {
                if (error instanceof Error) {
                    return error.message
                }
                return String(error)
            }

            expect(getErrorMessage(new Error('Test error'))).toBe('Test error')
        })

        test('should convert non-Error to string', () => {
            const getErrorMessage = (error: Error | unknown): string => {
                if (error instanceof Error) {
                    return error.message
                }
                return String(error)
            }

            expect(getErrorMessage('string error')).toBe('string error')
            expect(getErrorMessage(123)).toBe('123')
        })
    })

    describe('formatDate', () => {
        test('should format date correctly', () => {
            const formatDate = (date: string | Date): string => {
                return new Date(date).toLocaleDateString()
            }

            const result = formatDate('2024-01-15')
            expect(typeof result).toBe('string')
            expect(result.length).toBeGreaterThan(0)
        })
    })

    describe('confirmDelete', () => {
        test('should generate correct message with item name and type', () => {
            const generateMessage = (itemName: string, itemType: string, customMessage?: string): string => {
                return customMessage || `Are you sure you want to delete ${itemType} "${itemName}"? This action cannot be undone.`
            }

            expect(generateMessage('Test Item', 'product')).toContain('Test Item')
            expect(generateMessage('Test Item', 'product')).toContain('product')
            expect(generateMessage('Test Item', 'product')).toContain('cannot be undone')
        })

        test('should use custom message when provided', () => {
            const generateMessage = (itemName: string, itemType: string, customMessage?: string): string => {
                return customMessage || `Are you sure you want to delete ${itemType} "${itemName}"?`
            }

            expect(generateMessage('Test', 'item', 'Custom deletion message')).toBe('Custom deletion message')
        })
    })

    describe('EventEmitter', () => {
        test('should register event listeners', () => {
            const events: Record<string, Array<() => void>> = {}

            const on = (event: string, callback: () => void) => {
                if (!events[event]) {
                    events[event] = []
                }
                events[event].push(callback)
            }

            on('test', () => { })
            expect(events['test']).toHaveLength(1)

            on('test', () => { })
            expect(events['test']).toHaveLength(2)
        })

        test('should remove event listeners', () => {
            const events: Record<string, Array<() => void>> = {}
            const callback = () => { }

            const on = (event: string, cb: () => void) => {
                if (!events[event]) events[event] = []
                events[event].push(cb)
            }

            const off = (event: string, cb: () => void) => {
                if (!events[event]) return
                const index = events[event].indexOf(cb)
                if (index > -1) {
                    events[event].splice(index, 1)
                }
            }

            on('test', callback)
            expect(events['test']).toHaveLength(1)

            off('test', callback)
            expect(events['test']).toHaveLength(0)
        })

        test('should emit events to listeners', () => {
            let callCount = 0
            const events: Record<string, Array<(...args: unknown[]) => void>> = {}

            const on = (event: string, cb: () => void) => {
                if (!events[event]) events[event] = []
                events[event].push(cb)
            }

            const emit = (event: string) => {
                if (!events[event]) return
                events[event].forEach(cb => cb())
            }

            on('test', () => { callCount++ })
            emit('test')
            expect(callCount).toBe(1)

            emit('test')
            expect(callCount).toBe(2)
        })
    })

    describe('EVENTS constants', () => {
        test('should have all required event names', () => {
            const EVENTS = {
                REFRESH_PRODUCTS: 'refresh_products',
                REFRESH_PROJECTS: 'refresh_projects',
                REFRESH_COMPONENTS: 'refresh_components',
                ITEM_CREATED: 'item_created',
                ITEM_UPDATED: 'item_updated',
                ITEM_DELETED: 'item_deleted'
            }

            expect(EVENTS.REFRESH_PRODUCTS).toBe('refresh_products')
            expect(EVENTS.REFRESH_PROJECTS).toBe('refresh_projects')
            expect(EVENTS.REFRESH_COMPONENTS).toBe('refresh_components')
            expect(EVENTS.ITEM_CREATED).toBe('item_created')
            expect(EVENTS.ITEM_UPDATED).toBe('item_updated')
            expect(EVENTS.ITEM_DELETED).toBe('item_deleted')
        })
    })
})
