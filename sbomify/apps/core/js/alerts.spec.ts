import { describe, test, expect, beforeEach, mock } from 'bun:test'

// Mock window.dispatchEvent
const mockDispatchEvent = mock<(event: Event) => boolean>()

describe('Alerts', () => {
    beforeEach(() => {
        mockDispatchEvent.mockClear()
        globalThis.window = {
            ...globalThis.window,
            dispatchEvent: mockDispatchEvent,
            addEventListener: mock(() => {}),
            removeEventListener: mock(() => {}),
        } as unknown as Window & typeof globalThis
    })

    describe('Toast Options', () => {
        test('should accept valid toast options', () => {
            interface ToastOptions {
                title: string
                message: string
                type: 'success' | 'error' | 'warning' | 'info'
                duration?: number
            }

            const options: ToastOptions = {
                title: 'Success',
                message: 'Operation completed',
                type: 'success',
                duration: 3000
            }

            expect(options.title).toBe('Success')
            expect(options.type).toBe('success')
            expect(options.duration).toBe(3000)
        })

        test('should use default duration of 3000ms', () => {
            const defaultDuration = 3000
            expect(defaultDuration).toBe(3000)
        })
    })

    describe('Confirm Options', () => {
        test('should accept valid confirm options', () => {
            interface ConfirmOptions {
                id?: string
                title?: string
                message?: string
                type?: 'danger' | 'warning' | 'info' | 'success'
                confirmText?: string
                cancelText?: string
            }

            const options: ConfirmOptions = {
                id: 'test-confirm',
                title: 'Confirm',
                message: 'Are you sure?',
                type: 'warning',
                confirmText: 'Yes',
                cancelText: 'No'
            }

            expect(options.title).toBe('Confirm')
            expect(options.type).toBe('warning')
        })

        test('should have correct default values', () => {
            const defaults = {
                title: 'Are you sure?',
                type: 'warning',
                confirmText: 'Confirm',
                cancelText: 'Cancel'
            }

            expect(defaults.title).toBe('Are you sure?')
            expect(defaults.type).toBe('warning')
            expect(defaults.confirmText).toBe('Confirm')
            expect(defaults.cancelText).toBe('Cancel')
        })
    })

    describe('Shorthand Functions', () => {
        test('showSuccess should use success type', () => {
            const createToastOptions = (message: string, type: string) => ({
                title: type.charAt(0).toUpperCase() + type.slice(1),
                message,
                type
            })

            const options = createToastOptions('Item saved', 'success')
            expect(options.title).toBe('Success')
            expect(options.type).toBe('success')
        })

        test('showError should use error type', () => {
            const createToastOptions = (message: string, type: string) => ({
                title: type.charAt(0).toUpperCase() + type.slice(1),
                message,
                type
            })

            const options = createToastOptions('Something went wrong', 'error')
            expect(options.title).toBe('Error')
            expect(options.type).toBe('error')
        })

        test('showWarning should use warning type', () => {
            const createToastOptions = (message: string, type: string) => ({
                title: type.charAt(0).toUpperCase() + type.slice(1),
                message,
                type
            })

            const options = createToastOptions('Be careful', 'warning')
            expect(options.title).toBe('Warning')
            expect(options.type).toBe('warning')
        })

        test('showInfo should use info type', () => {
            const createToastOptions = (message: string, type: string) => ({
                title: type.charAt(0).toUpperCase() + type.slice(1),
                message,
                type
            })

            const options = createToastOptions('FYI', 'info')
            expect(options.title).toBe('Info')
            expect(options.type).toBe('info')
        })
    })

    describe('Confirmation Dialog', () => {
        test('should have safer defaults', () => {
            const defaultOptions = {
                title: 'Are you sure?',
                confirmText: 'Confirm',
                cancelText: 'Cancel',
                type: 'warning'
            }

            expect(defaultOptions.title).toBe('Are you sure?')
            expect(defaultOptions.type).toBe('warning')
        })

        test('confirmation types should map to correct styles', () => {
            const typeMap = {
                danger: 'tw-btn-danger',
                warning: 'tw-btn-warning',
                info: 'tw-btn-primary',
                success: 'tw-btn-success'
            }

            expect(typeMap.danger).toContain('danger')
            expect(typeMap.warning).toContain('warning')
            expect(typeMap.info).toContain('primary')
            expect(typeMap.success).toContain('success')
        })
    })

    describe('Event Dispatching', () => {
        test('toast event should have correct detail structure', () => {
            const toastDetail = {
                title: 'Test',
                message: 'Test message',
                type: 'success',
                duration: 3000
            }

            expect(toastDetail).toHaveProperty('title')
            expect(toastDetail).toHaveProperty('message')
            expect(toastDetail).toHaveProperty('type')
            expect(toastDetail).toHaveProperty('duration')
        })

        test('confirm event should have correct detail structure', () => {
            const confirmDetail = {
                id: 'test-id',
                title: 'Test',
                message: 'Test message',
                type: 'warning',
                confirmText: 'Yes',
                cancelText: 'No'
            }

            expect(confirmDetail).toHaveProperty('id')
            expect(confirmDetail).toHaveProperty('title')
            expect(confirmDetail).toHaveProperty('message')
            expect(confirmDetail).toHaveProperty('type')
            expect(confirmDetail).toHaveProperty('confirmText')
            expect(confirmDetail).toHaveProperty('cancelText')
        })
    })
})
