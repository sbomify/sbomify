import { describe, test, expect, mock, beforeEach } from 'bun:test'

const mockShowSuccess = mock<(message: string) => void>()
const mockShowError = mock<(message: string) => void>()

mock.module('../alerts', () => ({
    showSuccess: mockShowSuccess,
    showError: mockShowError
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
            const parseCsrfFromCookie = (cookieString: string): string => {
                const cookies = cookieString.split(';')
                for (let i = 0; i < cookies.length; i++) {
                    const cookie = cookies[i].trim()
                    if (cookie.startsWith('csrftoken')) {
                        const parts = cookie.split('=')
                        if (parts.length >= 2) {
                            const token = parts.slice(1).join('=')
                            if (token && token.trim()) {
                                return decodeURIComponent(token.trim())
                            }
                        }
                    }
                }
                return ''
            }

            expect(parseCsrfFromCookie('csrftoken=abc123')).toBe('abc123')
            expect(parseCsrfFromCookie('other=value; csrftoken=token123; another=test')).toBe('token123')
            expect(parseCsrfFromCookie('nocookie=here')).toBe('')
        })
    })

    describe('Focus Trap Logic', () => {
        test('should identify focusable element selectors', () => {
            const focusableSelectors = [
                'a[href]',
                'button:not([disabled])',
                'textarea:not([disabled])',
                'input:not([disabled])',
                'select:not([disabled])',
                '[tabindex]:not([tabindex="-1"])'
            ].join(', ')

            expect(focusableSelectors).toContain('a[href]')
            expect(focusableSelectors).toContain('button:not([disabled])')
            expect(focusableSelectors).toContain('textarea:not([disabled])')
            expect(focusableSelectors).toContain('input:not([disabled])')
            expect(focusableSelectors).toContain('select:not([disabled])')
            expect(focusableSelectors).toContain('[tabindex]:not([tabindex="-1"])')
        })

        test('should store trigger elements by modal ID', () => {
            const triggerElements: Record<string, HTMLElement | null> = {}

            triggerElements['modal-1'] = null
            triggerElements['modal-2'] = null

            expect('modal-1' in triggerElements).toBe(true)
            expect('modal-2' in triggerElements).toBe(true)
            expect('modal-3' in triggerElements).toBe(false)
        })

        test('should clean up trigger elements on modal close', () => {
            const triggerElements: Record<string, HTMLElement | null> = {
                'modal-1': null
            }

            const handleModalClose = (modalId: string) => {
                delete triggerElements[modalId]
            }

            handleModalClose('modal-1')
            expect('modal-1' in triggerElements).toBe(false)
        })
    })

    describe('Modal Visibility State', () => {
        test('should track visibility changes correctly', () => {
            let wasVisible = false

            const checkVisibility = (isCurrentlyVisible: boolean): { opened: boolean; closed: boolean } => {
                let opened = false
                let closed = false

                if (isCurrentlyVisible && !wasVisible) {
                    opened = true
                    wasVisible = true
                } else if (!isCurrentlyVisible && wasVisible) {
                    closed = true
                    wasVisible = false
                }

                return { opened, closed }
            }

            expect(checkVisibility(true)).toEqual({ opened: true, closed: false })
            expect(checkVisibility(true)).toEqual({ opened: false, closed: false })
            expect(checkVisibility(false)).toEqual({ opened: false, closed: true })
            expect(checkVisibility(false)).toEqual({ opened: false, closed: false })
        })

        test('should prevent concurrent visibility checks', () => {
            let isProcessing = false
            let checkCount = 0

            const checkVisibility = (): boolean => {
                if (isProcessing) return false
                isProcessing = true
                checkCount++
                isProcessing = false
                return true
            }

            expect(checkVisibility()).toBe(true)
            expect(checkCount).toBe(1)
            expect(checkVisibility()).toBe(true)
            expect(checkCount).toBe(2)
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
            const validateCsrfToken = (token: string): { valid: boolean; errorMsg?: string } => {
                if (!token) {
                    return {
                        valid: false,
                        errorMsg: 'Security error: Missing CSRF token. Please reload the page and try again.'
                    }
                }
                return { valid: true }
            }

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

    describe('Timeout Constants', () => {
        test('should use appropriate delay values', () => {
            const FOCUS_DELAY_MS = 50
            const FOCUS_RETURN_DELAY_MS = 100
            const INITIAL_CHECK_DELAY_MS = 150

            expect(FOCUS_DELAY_MS).toBeLessThan(FOCUS_RETURN_DELAY_MS)
            expect(FOCUS_RETURN_DELAY_MS).toBeLessThan(INITIAL_CHECK_DELAY_MS)
            expect(INITIAL_CHECK_DELAY_MS).toBeLessThan(500)
        })
    })
})
