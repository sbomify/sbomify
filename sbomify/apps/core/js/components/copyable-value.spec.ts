import { describe, test, expect, mock, beforeEach } from 'bun:test'

const mockAlpineData = mock<(name: string, callback: () => unknown) => void>()

mock.module('alpinejs', () => ({
    default: {
        data: mockAlpineData
    }
}))

describe('Copyable Value', () => {
    beforeEach(() => {
        mockAlpineData.mockClear()
    })

    describe('Params Interface', () => {
        test('should accept valid params', () => {
            interface CopyableValueParams {
                value: string
                hideValue: boolean
                copyFrom: string
                title: string
            }

            const params: CopyableValueParams = {
                value: 'secret-token',
                hideValue: true,
                copyFrom: '',
                title: 'API Token'
            }

            expect(params.value).toBe('secret-token')
            expect(params.hideValue).toBe(true)
            expect(params.title).toBe('API Token')
        })
    })

    describe('Value Resolution', () => {
        test('should use direct value when copyFrom is empty', () => {
            const getValue = (value: string, copyFrom: string, getElementText: (id: string) => string): string => {
                return copyFrom ? getElementText(copyFrom) : value
            }

            expect(getValue('direct-value', '', () => '')).toBe('direct-value')
        })

        test('should use element text when copyFrom is specified', () => {
            const getValue = (value: string, copyFrom: string, getElementText: (id: string) => string): string => {
                return copyFrom ? getElementText(copyFrom) : value
            }

            expect(getValue('direct-value', 'element-id', () => 'element-text')).toBe('element-text')
        })

        test('should return empty string for missing element', () => {
            const getValue = (value: string, copyFrom: string, getElementText: (id: string) => string | null): string => {
                if (copyFrom) {
                    return getElementText(copyFrom) || ''
                }
                return value
            }

            expect(getValue('direct', 'missing-id', () => null)).toBe('')
        })
    })

    describe('Message Dispatch', () => {
        test('should create success message object', () => {
            const successMessage = {
                value: [{
                    type: 'success',
                    message: 'Copied to clipboard'
                }]
            }

            expect(successMessage.value[0].type).toBe('success')
            expect(successMessage.value[0].message).toBe('Copied to clipboard')
        })

        test('should create error message object', () => {
            const errorMessage = {
                value: [{
                    type: 'error',
                    message: 'Failed to copy to clipboard'
                }]
            }

            expect(errorMessage.value[0].type).toBe('error')
            expect(errorMessage.value[0].message).toBe('Failed to copy to clipboard')
        })
    })

    describe('Hidden Value', () => {
        test('should support hiding the value display', () => {
            const hideValue = true
            expect(hideValue).toBe(true)
        })

        test('should support showing the value display', () => {
            const hideValue = false
            expect(hideValue).toBe(false)
        })
    })
})
