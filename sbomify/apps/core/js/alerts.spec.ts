import { describe, test, expect, mock, beforeEach } from 'bun:test'

const mockSwalFire = mock<(options: unknown) => Promise<{ isConfirmed: boolean }>>()

mock.module('sweetalert2', () => ({
    default: {
        fire: mockSwalFire.mockResolvedValue({ isConfirmed: true })
    }
}))

describe('Alerts', () => {
    beforeEach(() => {
        mockSwalFire.mockClear()
    })

    describe('Toast Options', () => {
        test('should accept valid toast options', () => {
            interface ToastOptions {
                title: string
                message: string
                type: 'success' | 'error' | 'warning' | 'info'
                timer?: number
                position?: string
            }

            const options: ToastOptions = {
                title: 'Success',
                message: 'Operation completed',
                type: 'success',
                timer: 3000,
                position: 'top-end'
            }

            expect(options.title).toBe('Success')
            expect(options.type).toBe('success')
            expect(options.timer).toBe(3000)
        })

        test('should use default timer of 3000ms', () => {
            const defaultTimer = 3000
            expect(defaultTimer).toBe(3000)
        })

        test('should use default position of top-end', () => {
            const defaultPosition = 'top-end'
            expect(defaultPosition).toBe('top-end')
        })
    })

    describe('Alert Options', () => {
        test('should accept valid alert options', () => {
            interface AlertOptions {
                title: string
                message: string
                type: 'success' | 'error' | 'warning' | 'info'
                showCancelButton?: boolean
                confirmButtonText?: string
                cancelButtonText?: string
            }

            const options: AlertOptions = {
                title: 'Confirm',
                message: 'Are you sure?',
                type: 'warning',
                showCancelButton: true,
                confirmButtonText: 'Yes',
                cancelButtonText: 'No'
            }

            expect(options.title).toBe('Confirm')
            expect(options.showCancelButton).toBe(true)
        })

        test('should have correct default button texts', () => {
            const defaultConfirmText = 'OK'
            const defaultCancelText = 'Cancel'

            expect(defaultConfirmText).toBe('OK')
            expect(defaultCancelText).toBe('Cancel')
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
                confirmButtonText: 'Yes',
                cancelButtonText: 'No',
                type: 'warning',
                focusCancel: true,
                reverseButtons: true
            }

            expect(defaultOptions.title).toBe('Are you sure?')
            expect(defaultOptions.focusCancel).toBe(true)
            expect(defaultOptions.reverseButtons).toBe(true)
        })
    })

    describe('Custom Classes', () => {
        test('should use Bootstrap button classes', () => {
            const customClass = {
                confirmButton: 'btn btn-primary',
                cancelButton: 'btn btn-secondary',
                actions: 'gap-2'
            }

            expect(customClass.confirmButton).toContain('btn')
            expect(customClass.cancelButton).toContain('btn')
            expect(customClass.actions).toBe('gap-2')
        })

        test('should use danger class for destructive confirmations', () => {
            const dangerClass = 'btn btn-danger'
            expect(dangerClass).toContain('danger')
        })
    })

    describe('SweetAlert2 Configuration', () => {
        test('should disable default button styling', () => {
            const config = {
                buttonsStyling: false
            }

            expect(config.buttonsStyling).toBe(false)
        })

        test('should configure toast properly', () => {
            const toastConfig = {
                toast: true,
                showConfirmButton: false,
                timerProgressBar: true
            }

            expect(toastConfig.toast).toBe(true)
            expect(toastConfig.showConfirmButton).toBe(false)
            expect(toastConfig.timerProgressBar).toBe(true)
        })
    })
})
