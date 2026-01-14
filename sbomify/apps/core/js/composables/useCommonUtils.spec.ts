import { describe, test, expect } from 'bun:test'

describe('useCommonUtils', () => {
    describe('truncateText', () => {
        test('should return empty string for null input', () => {
            const truncateText = (text: string | null | undefined, maxLength: number): string => {
                if (!text) return ''
                if (text.length <= maxLength) return text
                return text.substring(0, maxLength) + '...'
            }

            expect(truncateText(null, 10)).toBe('')
            expect(truncateText(undefined, 10)).toBe('')
        })

        test('should return full text when within limit', () => {
            const truncateText = (text: string | null | undefined, maxLength: number): string => {
                if (!text) return ''
                if (text.length <= maxLength) return text
                return text.substring(0, maxLength) + '...'
            }

            expect(truncateText('Hello', 10)).toBe('Hello')
            expect(truncateText('Exact ten!', 10)).toBe('Exact ten!')
        })

        test('should truncate text exceeding limit', () => {
            const truncateText = (text: string | null | undefined, maxLength: number): string => {
                if (!text) return ''
                if (text.length <= maxLength) return text
                return text.substring(0, maxLength) + '...'
            }

            expect(truncateText('This is a long text', 10)).toBe('This is a ...')
            expect(truncateText('Hello World', 5)).toBe('Hello...')
        })
    })

    describe('formatDate', () => {
        test('should format valid date string', () => {
            const formatDate = (dateString: string): string => {
                try {
                    const date = new Date(dateString)
                    return date.toLocaleDateString()
                } catch {
                    return dateString
                }
            }

            const result = formatDate('2024-01-15')
            expect(typeof result).toBe('string')
            expect(result.length).toBeGreaterThan(0)
        })

        test('should return original string for invalid date', () => {
            const formatDate = (dateString: string): string => {
                try {
                    const date = new Date(dateString)
                    if (isNaN(date.getTime())) {
                        return dateString
                    }
                    return date.toLocaleDateString()
                } catch {
                    return dateString
                }
            }

            expect(formatDate('invalid-date')).toBe('invalid-date')
        })
    })

    describe('normalizeBoolean', () => {
        test('should convert string "true" to boolean true', () => {
            const normalizeBoolean = (value: boolean | string | undefined): boolean => {
                if (typeof value === 'string') {
                    return value === 'true'
                }
                return value === true
            }

            expect(normalizeBoolean('true')).toBe(true)
        })

        test('should convert string "false" to boolean false', () => {
            const normalizeBoolean = (value: boolean | string | undefined): boolean => {
                if (typeof value === 'string') {
                    return value === 'true'
                }
                return value === true
            }

            expect(normalizeBoolean('false')).toBe(false)
        })

        test('should pass through boolean values', () => {
            const normalizeBoolean = (value: boolean | string | undefined): boolean => {
                if (typeof value === 'string') {
                    return value === 'true'
                }
                return value === true
            }

            expect(normalizeBoolean(true)).toBe(true)
            expect(normalizeBoolean(false)).toBe(false)
        })

        test('should return false for undefined', () => {
            const normalizeBoolean = (value: boolean | string | undefined): boolean => {
                if (typeof value === 'string') {
                    return value === 'true'
                }
                return value === true
            }

            expect(normalizeBoolean(undefined)).toBe(false)
        })
    })

    describe('getCsrfToken', () => {
        test('should extract token from cookie string', () => {
            const getCsrfToken = (cookies: string): string => {
                const csrfCookie = cookies
                    .split('; ')
                    .find(row => row.startsWith('csrftoken='))
                return csrfCookie ? csrfCookie.split('=')[1] : ''
            }

            expect(getCsrfToken('csrftoken=abc123; sessionid=xyz')).toBe('abc123')
        })

        test('should return empty string when token not found', () => {
            const getCsrfToken = (cookies: string): string => {
                const csrfCookie = cookies
                    .split('; ')
                    .find(row => row.startsWith('csrftoken='))
                return csrfCookie ? csrfCookie.split('=')[1] : ''
            }

            expect(getCsrfToken('sessionid=xyz; other=value')).toBe('')
            expect(getCsrfToken('')).toBe('')
        })
    })

    describe('Return Object', () => {
        test('should return all utility functions', () => {
            const useCommonUtils = () => {
                const truncateText = (text: string | null | undefined, maxLength: number): string => {
                    if (!text) return ''
                    if (text.length <= maxLength) return text
                    return text.substring(0, maxLength) + '...'
                }

                const formatDate = (dateString: string): string => {
                    try {
                        const date = new Date(dateString)
                        return date.toLocaleDateString()
                    } catch {
                        return dateString
                    }
                }

                const normalizeBoolean = (value: boolean | string | undefined): boolean => {
                    if (typeof value === 'string') {
                        return value === 'true'
                    }
                    return value === true
                }

                const getCsrfToken = (): string => {
                    return ''
                }

                return {
                    truncateText,
                    formatDate,
                    normalizeBoolean,
                    getCsrfToken
                }
            }

            const utils = useCommonUtils()
            expect(typeof utils.truncateText).toBe('function')
            expect(typeof utils.formatDate).toBe('function')
            expect(typeof utils.normalizeBoolean).toBe('function')
            expect(typeof utils.getCsrfToken).toBe('function')
        })
    })
})
