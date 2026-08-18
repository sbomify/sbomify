import { describe, test, expect, mock, beforeEach } from 'bun:test'

const mockAlpineData = mock<(name: string, callback: () => unknown) => void>()

mock.module('alpinejs', () => ({
    default: {
        data: mockAlpineData
    }
}))

// Imported after the Alpine mock is installed so the real module registers against it.
const { registerCopyableValue } = await import('./copyable-value')

interface CopyableValueParams {
    value: string
    hideValue: boolean
    copyFrom: string
    title: string
}

interface Component {
    value: string
    copyFrom: string
    copied: boolean
    copyToClipboard(): void
    destroy(): void
    $dispatch: ReturnType<typeof mock>
}

/** Builds the real Alpine component, with the clipboard and $dispatch stubbed. */
function build(params: Partial<CopyableValueParams> = {}, writeText?: ReturnType<typeof mock>) {
    mockAlpineData.mockClear()
    registerCopyableValue()
    const factory = mockAlpineData.mock.calls[0]![1] as unknown as (p: CopyableValueParams) => Component

    const clipboardWrite = writeText ?? mock(() => Promise.resolve())
    Object.defineProperty(globalThis, 'navigator', {
        value: { clipboard: { writeText: clipboardWrite } },
        configurable: true,
        writable: true
    })

    const component = factory({
        value: 'sbom-1',
        hideValue: false,
        copyFrom: '',
        title: 'Copy id',
        ...params
    })
    component.$dispatch = mock(() => undefined)
    return { component, clipboardWrite }
}

describe('Copyable Value', () => {
    beforeEach(() => {
        mockAlpineData.mockClear()
    })

    describe('Copy confirmation', () => {
        // The chip confirms in place. It used to dispatch a success toast, which was
        // far too loud for something that sits in every page header.
        test('enters the copied state and dispatches no toast on success', async () => {
            const { component, clipboardWrite } = build({ value: 'DLyQjCBkNJkB' })

            expect(component.copied).toBe(false)
            component.copyToClipboard()
            await Promise.resolve()

            expect(clipboardWrite).toHaveBeenCalledWith('DLyQjCBkNJkB')
            expect(component.copied).toBe(true)
            expect(component.$dispatch).not.toHaveBeenCalled()
            component.destroy()
        })

        test('leaves the copied state again', async () => {
            const { component } = build()
            component.copyToClipboard()
            await Promise.resolve()
            expect(component.copied).toBe(true)

            await new Promise(resolve => setTimeout(resolve, 1700))
            expect(component.copied).toBe(false)
        })

        test('still reports a genuine failure, which the chip cannot show', async () => {
            const failing = mock(() => Promise.reject(new Error('denied')))
            const { component } = build({}, failing)

            // The component logs the rejection; keep it out of the test output.
            const consoleError = console.error
            console.error = () => undefined

            component.copyToClipboard()
            await new Promise(resolve => setTimeout(resolve, 0))
            console.error = consoleError

            expect(component.copied).toBe(false)
            expect(component.$dispatch).toHaveBeenCalled()
            const [event, payload] = component.$dispatch.mock.calls[0] as [string, { value: { type: string }[] }]
            expect(event).toBe('messages')
            expect(payload.value[0].type).toBe('error')
        })
    })

    describe('Value resolution', () => {
        test('copies the direct value when copyFrom is empty', async () => {
            const { component, clipboardWrite } = build({ value: 'direct-value' })
            component.copyToClipboard()
            await Promise.resolve()
            expect(clipboardWrite).toHaveBeenCalledWith('direct-value')
            component.destroy()
        })

        test('copies the referenced element text when copyFrom is set', async () => {
            Object.defineProperty(globalThis, 'document', {
                value: { getElementById: (id: string) => (id === 'src' ? { innerText: 'element-text' } : null) },
                configurable: true,
                writable: true
            })
            const { component, clipboardWrite } = build({ value: 'ignored', copyFrom: 'src' })
            component.copyToClipboard()
            await Promise.resolve()
            expect(clipboardWrite).toHaveBeenCalledWith('element-text')
            component.destroy()
        })

        test('copies an empty string when the referenced element is missing', async () => {
            Object.defineProperty(globalThis, 'document', {
                value: { getElementById: () => null },
                configurable: true,
                writable: true
            })
            const { component, clipboardWrite } = build({ value: 'ignored', copyFrom: 'missing' })
            component.copyToClipboard()
            await Promise.resolve()
            expect(clipboardWrite).toHaveBeenCalledWith('')
            component.destroy()
        })
    })
})
