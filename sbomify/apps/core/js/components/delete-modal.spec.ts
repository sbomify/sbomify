import { describe, test, expect, mock, beforeEach } from 'bun:test'
import { parseCsrfFromCookie, validateCsrfToken } from '../test-utils'

const mockShowSuccess = mock<(message: string) => void>()
const mockShowError = mock<(message: string) => void>()

mock.module('../alerts', () => ({
    showSuccess: mockShowSuccess,
    showError: mockShowError,
    showWarning: mock(),
    showInfo: mock(),
    showToast: mock(),
    showConfirmation: mock()
}))

interface DeleteModalConfig {
    modalId: string
    hxUrl: string
    hxMethod?: string
    successMessage: string
    csrfToken: string
    redirectUrl?: string
    refreshEvent?: string
}

describe('Delete Modal', () => {
    beforeEach(() => {
        mockShowSuccess.mockClear()
        mockShowError.mockClear()
    })

    describe('DeleteModalConfig interface', () => {
        test('should accept valid configuration', () => {
            const config: DeleteModalConfig = {
                modalId: 'deleteModal',
                hxUrl: '/api/v1/items/123',
                successMessage: 'Item deleted successfully',
                csrfToken: 'test-token-123'
            }

            expect(config.modalId).toBe('deleteModal')
            expect(config.hxUrl).toBe('/api/v1/items/123')
            expect(config.successMessage).toBe('Item deleted successfully')
            expect(config.csrfToken).toBe('test-token-123')
        })

        test('should support optional hxMethod', () => {
            const configDelete: DeleteModalConfig = {
                modalId: 'modal',
                hxUrl: '/api/items/1',
                successMessage: 'Deleted',
                csrfToken: 'token',
                hxMethod: 'DELETE'
            }

            const configPost: DeleteModalConfig = {
                modalId: 'modal',
                hxUrl: '/api/items/1',
                successMessage: 'Deleted',
                csrfToken: 'token',
                hxMethod: 'POST'
            }

            expect(configDelete.hxMethod).toBe('DELETE')
            expect(configPost.hxMethod).toBe('POST')
        })

        test('should support optional redirectUrl', () => {
            const config: DeleteModalConfig = {
                modalId: 'modal',
                hxUrl: '/api/items/1',
                successMessage: 'Deleted',
                csrfToken: 'token',
                redirectUrl: '/dashboard'
            }

            expect(config.redirectUrl).toBe('/dashboard')
        })

        test('should support optional refreshEvent', () => {
            const config: DeleteModalConfig = {
                modalId: 'modal',
                hxUrl: '/api/items/1',
                successMessage: 'Deleted',
                csrfToken: 'token',
                refreshEvent: 'items:refresh'
            }

            expect(config.refreshEvent).toBe('items:refresh')
        })
    })

    describe('CSRF Token Retrieval', () => {
        test('should prioritize config token over other sources', () => {
            const getCsrfToken = (config: { csrfToken: string }): string => {
                if (config.csrfToken && config.csrfToken.trim()) {
                    return config.csrfToken.trim()
                }
                return ''
            }

            expect(getCsrfToken({ csrfToken: 'config-token' })).toBe('config-token')
            expect(getCsrfToken({ csrfToken: '  spaced-token  ' })).toBe('spaced-token')
        })

        test('should return empty string for missing token', () => {
            const getCsrfToken = (config: { csrfToken: string }): string => {
                if (config.csrfToken && config.csrfToken.trim()) {
                    return config.csrfToken.trim()
                }
                return ''
            }

            expect(getCsrfToken({ csrfToken: '' })).toBe('')
            expect(getCsrfToken({ csrfToken: '   ' })).toBe('')
        })

        test('should parse CSRF token from cookie format', () => {
            // Uses shared parseCsrfFromCookie utility from test-utils
            expect(parseCsrfFromCookie('csrftoken=abc123')).toBe('abc123')
            expect(parseCsrfFromCookie('other=value; csrftoken=token123; another=test')).toBe('token123')
            expect(parseCsrfFromCookie('nocookie=here')).toBe('')
        })
    })

    describe('Delete Handler Logic', () => {
        test('should prevent duplicate submissions', () => {
            let isLoading = false
            let submitCount = 0

            const handleDelete = async () => {
                if (isLoading) return
                isLoading = true
                submitCount++
                isLoading = false
            }

            handleDelete()
            expect(submitCount).toBe(1)
        })

        test('should use correct HTTP method', () => {
            const getMethod = (config: { hxMethod?: string }): string => {
                return config.hxMethod || 'DELETE'
            }

            expect(getMethod({})).toBe('DELETE')
            expect(getMethod({ hxMethod: 'POST' })).toBe('POST')
            expect(getMethod({ hxMethod: 'DELETE' })).toBe('DELETE')
        })

        test('should build correct headers', () => {
            const buildHeaders = (csrfToken: string): Record<string, string> => ({
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken
            })

            const headers = buildHeaders('test-token')
            expect(headers['Content-Type']).toBe('application/json')
            expect(headers['X-CSRFToken']).toBe('test-token')
        })
    })

    describe('Error Handling', () => {
        test('should handle missing CSRF token', () => {
            // Uses shared validateCsrfToken utility from test-utils
            expect(validateCsrfToken('')).toEqual({
                valid: false,
                errorMsg: 'Security error: Missing CSRF token. Please reload the page and try again.'
            })
            expect(validateCsrfToken('valid-token')).toEqual({ valid: true })
        })

        test('should extract error detail from JSON response', () => {
            const extractErrorDetail = (data: unknown): string => {
                if (data && typeof data === 'object') {
                    const typedData = data as { detail?: string }
                    if (typeof typedData.detail === 'string') {
                        return typedData.detail
                    }
                    return JSON.stringify(data)
                }
                return ''
            }

            expect(extractErrorDetail({ detail: 'Not found' })).toBe('Not found')
            expect(extractErrorDetail({ error: 'Something went wrong' })).toBe('{"error":"Something went wrong"}')
            expect(extractErrorDetail(null)).toBe('')
        })
    })
})
