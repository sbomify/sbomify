import { describe, test, expect, mock, spyOn, beforeEach, afterEach } from 'bun:test'

const showError = mock<(message: string) => void>()
const showSuccess = mock<(message: string) => void>()

mock.module('./alerts', () => ({
    showError,
    showSuccess,
    showWarning: mock(),
    showInfo: mock(),
    showToast: mock(),
    showConfirmation: mock(),
}))

mock.module('./csrf', () => ({ getCsrfToken: () => 'csrf-value' }))

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Component = Record<string, any>
const factories: Record<string, (props: Record<string, unknown>) => Component> = {}

mock.module('./alpine-init', () => ({
    default: {
        data: (name: string, factory: (props: Record<string, unknown>) => Component) => {
            factories[name] = factory
        },
    },
}))

const { registerComponentMetaInfo } = await import('./component-meta-info')
const { registerComponentMetaInfoEditor } = await import('./component-meta-info-editor')
registerComponentMetaInfo()
registerComponentMetaInfoEditor()

const globals = globalThis as unknown as Record<string, unknown>
const realGlobals = { fetch: globals.fetch, window: globals.window }

function respond(response: Response | Error): ReturnType<typeof mock> {
    const fetcher = mock(async () => {
        if (response instanceof Error) throw response
        return response.clone()
    })
    globals.fetch = fetcher
    return fetcher
}

function wrapper(): Component {
    return factories.componentMetaInfoWrapper({ componentId: 'c1', teamKey: 't1', allowEdit: true })
}

function editor(): Component {
    const component = factories.componentMetaInfoEditor({ componentId: 'c1', teamKey: '', metadata: null, contactProfiles: [] })
    component.$dispatch = mock()
    return component
}

/** Every toast shown so far, in the order the tests expect to read them. */
function toasts(): [string, string][] {
    return [
        ...showSuccess.mock.calls.map(([message]): [string, string] => ['success', message]),
        ...showError.mock.calls.map(([message]): [string, string] => ['error', message]),
    ]
}

const settle = () => new Promise(resolve => setTimeout(resolve, 0))

describe('component metadata toasts', () => {
    let consoleError: ReturnType<typeof spyOn>

    beforeEach(() => {
        showError.mockClear()
        showSuccess.mockClear()
        consoleError = spyOn(console, 'error').mockImplementation(() => {})
        globals.window = new EventTarget()
    })

    afterEach(() => {
        consoleError.mockRestore()
        for (const [name, value] of Object.entries(realGlobals)) {
            if (value === undefined) delete globals[name]
            else globals[name] = value
        }
    })

    test('a failed metadata load shows one error', async () => {
        respond(new Response('', { status: 500 }))
        await wrapper().fetchMetadata()
        expect(toasts()).toEqual([['error', 'Failed to load component metadata']])
    })

    test('a network failure while loading shows one error', async () => {
        respond(new Error('offline'))
        await wrapper().fetchMetadata()
        expect(toasts()).toEqual([['error', 'Network error loading metadata']])
    })

    test('the editor shows one error when its load fails', async () => {
        respond(new Error('offline'))
        await editor().loadMetadata()
        expect(toasts()).toEqual([['error', 'Failed to load component metadata']])
    })

    test('a refused save shows one error with the server reason', async () => {
        respond(Response.json({ detail: 'Supplier name is too long' }, { status: 400 }))
        await editor().updateMetaData()
        expect(toasts()).toEqual([['error', 'Supplier name is too long']])
    })

    test('a successful save shows one toast and reloads the display once', async () => {
        const fetcher = respond(Response.json({}))
        const display = wrapper()
        display.init()
        await settle()
        const form = editor()
        // The template's @metadata-saved listener on the wrapper.
        form.$dispatch = (event: string) => {
            if (event === 'metadata-saved') display.refreshDisplay()
        }
        fetcher.mockClear()

        await form.updateMetaData()
        await settle()

        expect(toasts()).toEqual([['success', 'Metadata saved successfully']])
        expect(fetcher).toHaveBeenCalledTimes(2)
        expect(display.isEditing).toBe(false)
    })
})
