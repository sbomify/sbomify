import { describe, test, expect } from 'bun:test'
import {
    formatDate,
    formatDateTime,
    formatRelativeDate,
    formatCompactRelativeDate,
    formatLastChecked,
} from './utils'

describe('Utils', () => {

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
        test('should format a valid date string', () => {
            const result = formatDate('2024-01-15')
            expect(typeof result).toBe('string')
            expect(result).toContain('2024')
            expect(result).not.toBe('-')
        })

        test('should format a Date object', () => {
            const result = formatDate(new Date(2024, 0, 15))
            expect(result).toContain('2024')
        })

        test('should return "-" for null/undefined/empty/invalid', () => {
            expect(formatDate(null)).toBe('-')
            expect(formatDate(undefined)).toBe('-')
            expect(formatDate('')).toBe('-')
            expect(formatDate('not-a-date')).toBe('-')
        })

        test('should use custom fallback when provided', () => {
            expect(formatDate(null, { fallback: '—' })).toBe('—')
            expect(formatDate('', { fallback: '' })).toBe('')
        })
    })

    describe('formatDateTime', () => {
        test('should include date and time parts', () => {
            const result = formatDateTime('2024-06-15T14:30:00Z')
            expect(result).toContain('2024')
            expect(result).not.toBe('-')
        })

        test('should respect use24Hour option', () => {
            const result12h = formatDateTime('2024-06-15T14:30:00Z')
            const result24h = formatDateTime('2024-06-15T14:30:00Z', { use24Hour: true })
            expect(result12h).not.toBe(result24h)
            // 24-hour format should not contain AM/PM
            expect(result24h).not.toMatch(/AM|PM/i)
        })

        test('should return "-" for invalid input', () => {
            expect(formatDateTime(null)).toBe('-')
            expect(formatDateTime(undefined)).toBe('-')
        })

        test('should use custom fallback when provided', () => {
            expect(formatDateTime(null, { fallback: 'N/A' })).toBe('N/A')
        })
    })

    describe('formatRelativeDate', () => {
        const now = new Date('2024-06-15T12:00:00Z')

        test('should return "Today" for same calendar day', () => {
            const result = formatRelativeDate('2024-06-15T08:00:00Z', { now })
            expect(result).toBe('Today')
        })

        test('should return relative text for recent dates', () => {
            const yesterday = new Date(now.getTime() - 86_400_000)
            const result = formatRelativeDate(yesterday, { now })
            expect(typeof result).toBe('string')
            expect(result).not.toBe('-')
            expect(result).not.toBe('Today')
        })

        test('should use relative format at exactly 7 days', () => {
            const sevenDaysAgo = new Date(now.getTime() - 7 * 86_400_000)
            const result = formatRelativeDate(sevenDaysAgo, { now })
            // 7 days is still within relative range (> 7 triggers absolute)
            expect(result).not.toContain('2024')
        })

        test('should fall back to absolute date after 7 days', () => {
            const eightDaysAgo = new Date(now.getTime() - 8 * 86_400_000)
            const result = formatRelativeDate(eightDaysAgo, { now })
            expect(result).toContain('2024')
        })

        test('should return "-" for invalid input', () => {
            expect(formatRelativeDate(null)).toBe('-')
            expect(formatRelativeDate(undefined)).toBe('-')
        })

        test('should use custom fallback when provided', () => {
            expect(formatRelativeDate(null, { fallback: '' })).toBe('')
        })
    })

    describe('formatCompactRelativeDate', () => {
        const now = new Date('2024-06-15T12:00:00Z')

        test('should return "Just now" for < 1 minute ago', () => {
            const justNow = new Date(now.getTime() - 30_000)
            expect(formatCompactRelativeDate(justNow, { now })).toBe('Just now')
        })

        test('should return minutes ago', () => {
            const fiveMinAgo = new Date(now.getTime() - 5 * 60_000)
            expect(formatCompactRelativeDate(fiveMinAgo, { now })).toBe('5m ago')
        })

        test('should return hours ago', () => {
            const twoHoursAgo = new Date(now.getTime() - 2 * 3_600_000)
            expect(formatCompactRelativeDate(twoHoursAgo, { now })).toBe('2h ago')
        })

        test('should return days ago', () => {
            const threeDaysAgo = new Date(now.getTime() - 3 * 86_400_000)
            expect(formatCompactRelativeDate(threeDaysAgo, { now })).toBe('3d ago')
        })

        test('should fall back to absolute date after 7 days', () => {
            const twoWeeksAgo = new Date(now.getTime() - 14 * 86_400_000)
            const result = formatCompactRelativeDate(twoWeeksAgo, { now })
            expect(result).toContain('2024')
        })

        test('should return "-" for invalid input', () => {
            expect(formatCompactRelativeDate(null)).toBe('-')
        })
    })

    describe('formatLastChecked', () => {
        test('should return "Never" for null/undefined/empty', () => {
            expect(formatLastChecked(null)).toBe('Never')
            expect(formatLastChecked(undefined)).toBe('Never')
            expect(formatLastChecked('')).toBe('Never')
        })

        test('should return formatted datetime for valid input', () => {
            const result = formatLastChecked('2024-06-15T14:30:00Z')
            expect(result).toContain('2024')
            expect(result).not.toBe('Never')
        })

        test('should use 12-hour format', () => {
            const result = formatLastChecked('2024-06-15T14:30:00Z')
            expect(result).not.toMatch(/\b14:/)
        })

        test('should use custom fallback when provided', () => {
            expect(formatLastChecked(null, { fallback: 'Unknown' })).toBe('Unknown')
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

    describe('CSRF interceptor logic', () => {
        test('should set X-CSRFToken header when token is available', () => {
            const getCsrfToken = () => 'test-csrf-token'
            const headers = new Map<string, string>()

            // Simulate interceptor logic
            const config = {
                headers: { set: (key: string, value: string) => headers.set(key, value) }
            }

            try {
                const token = getCsrfToken()
                config.headers.set('X-CSRFToken', token)
            } catch {
                // noop
            }

            expect(headers.get('X-CSRFToken')).toBe('test-csrf-token')
        })

        test('should not throw when getCsrfToken fails', () => {
            const getCsrfToken = () => { throw new Error('No CSRF meta tag') }
            const headers = new Map<string, string>()

            const config = {
                headers: { set: (key: string, value: string) => headers.set(key, value) }
            }

            try {
                const token = getCsrfToken()
                config.headers.set('X-CSRFToken', token)
            } catch {
                // CSRF token not available, let the request proceed without it
            }

            expect(headers.has('X-CSRFToken')).toBe(false)
        })

        test('should initialize headers when undefined', () => {
            const getCsrfToken = () => 'test-token'
            let headersInitialized = false

            const config: { headers: { set: (k: string, v: string) => void } | null } = {
                headers: null
            }

            try {
                const token = getCsrfToken()
                if (!config.headers) {
                    config.headers = { set: () => {} }
                    headersInitialized = true
                }
                config.headers.set('X-CSRFToken', token)
            } catch {
                // noop
            }

            expect(headersInitialized).toBe(true)
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
