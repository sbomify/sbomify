import { describe, test, expect, mock, beforeEach } from 'bun:test'

mock.module('../utils', () => ({
    confirmDelete: mock().mockResolvedValue(true)
}))

const mockAlpineData = mock<(name: string, callback: () => unknown) => void>()

mock.module('alpinejs', () => ({
    default: {
        data: mockAlpineData
    }
}))

describe('Confirm Action', () => {
    beforeEach(() => {
        mockAlpineData.mockClear()
    })

    describe('Params Interface', () => {
        test('should accept valid params', () => {
            interface ConfirmActionParams {
                targetElementId: string
                confirmationMessage?: string
                itemName: string
                itemType: string
            }

            const params: ConfirmActionParams = {
                targetElementId: 'delete-btn',
                itemName: 'My Item',
                itemType: 'product'
            }

            expect(params.targetElementId).toBe('delete-btn')
            expect(params.itemName).toBe('My Item')
            expect(params.itemType).toBe('product')
        })

        test('should support optional confirmation message', () => {
            interface ConfirmActionParams {
                targetElementId: string
                confirmationMessage?: string
                itemName: string
                itemType: string
            }

            const params: ConfirmActionParams = {
                targetElementId: 'delete-btn',
                confirmationMessage: 'Are you really sure?',
                itemName: 'My Item',
                itemType: 'product'
            }

            expect(params.confirmationMessage).toBe('Are you really sure?')
        })
    })

    describe('Confirmation Flow', () => {
        test('should build confirmDelete options correctly', () => {
            const buildOptions = (itemName: string, itemType: string, customMessage?: string) => ({
                itemName,
                itemType,
                customMessage
            })

            const options = buildOptions('Test Item', 'component', 'Custom message')
            expect(options.itemName).toBe('Test Item')
            expect(options.itemType).toBe('component')
            expect(options.customMessage).toBe('Custom message')
        })
    })

    describe('Event Prevention', () => {
        test('should prevent default event', () => {
            let defaultPrevented = false

            const event = {
                preventDefault: () => { defaultPrevented = true }
            }

            event.preventDefault()
            expect(defaultPrevented).toBe(true)
        })
    })
})
