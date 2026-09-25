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
    copySelector?: string
    title: string
}

interface Component {
    value: string
    copyFrom: string
    copied: boolean
    copyToClipboard(): Promise<void>
    destroy(): void
    $dispatch: ReturnType<typeof mock>
    $el: HTMLElement
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
        test('reports an unavailable clipboard without claiming success', async () => {
            const { component } = build()
            Object.defineProperty(globalThis, 'navigator', { value: {}, configurable: true, writable: true })
            const consoleError = console.error
            console.error = () => undefined
            try {
                await component.copyToClipboard()
            } finally {
                console.error = consoleError
            }
            expect(component.copied).toBe(false)
            expect(component.$dispatch).toHaveBeenCalledWith('messages', {
                value: [{ type: 'error', message: 'Failed to copy to clipboard' }]
            })
        })

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
        test('reads current code from its own container, without the copy button label', async () => {
            let textContent = 'first command\n  --flag'
            const querySelector = mock(() => ({ get textContent() { return textContent } }))
            const closest = mock(() => ({ querySelector }))
            const { component, clipboardWrite } = build({ copySelector: 'code' })
            component.$el = { closest } as unknown as HTMLElement
            await component.copyToClipboard()
            expect(closest).toHaveBeenCalledWith('[data-copy-container]')
            expect(querySelector).toHaveBeenCalledWith('code')
            expect(clipboardWrite).toHaveBeenLastCalledWith('first command\n  --flag')
            textContent = 'updated command'
            await component.copyToClipboard()
            expect(clipboardWrite).toHaveBeenLastCalledWith('updated command')
            component.destroy()
        })

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

        test('trims a value read out of the DOM', async () => {
            // The token display reads its secret from the rendered element, which
            // carries the template's indentation. A token pasted with a trailing
            // newline fails wherever it is used and the user cannot see why.
            Object.defineProperty(globalThis, 'document', {
                value: { getElementById: (id: string) => (id === 'src' ? { innerText: '\n  sbom_pat_9f2A\n' } : null) },
                configurable: true,
                writable: true
            })
            const { component, clipboardWrite } = build({ value: 'ignored', copyFrom: 'src' })
            component.copyToClipboard()
            await Promise.resolve()
            expect(clipboardWrite).toHaveBeenCalledWith('sbom_pat_9f2A')
            component.destroy()
        })
    })

    describe('a failed write', () => {
        test('does not report success', async () => {
            // The secret is shown once. Reporting a copy that did not happen
            // costs the user the token with no way back to it.
            const rejecting = mock(() => Promise.reject(new Error('denied')))
            const { component } = build({ value: 'sbom_pat_9f2A' }, rejecting)
            await component.copyToClipboard()
            expect(component.copied).toBe(false)
            component.destroy()
        })

        test('interrupts with an error message', async () => {
            const rejecting = mock(() => Promise.reject(new Error('denied')))
            const { component } = build({ value: 'sbom_pat_9f2A' }, rejecting)
            await component.copyToClipboard()
            expect(component.$dispatch).toHaveBeenCalledWith('messages', {
                value: [{ type: 'error', message: 'Failed to copy to clipboard' }]
            })
            component.destroy()
        })
    })
})
