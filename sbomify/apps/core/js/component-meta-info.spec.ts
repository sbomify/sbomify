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
const realGlobals = { fetch: globals.fetch, document: globals.document, window: globals.window }

function respond(response: Response | Error): void {
    globals.fetch = mock(async () => {
        if (response instanceof Error) throw response
        return response
    })
}

function wrapper(): Component {
    return factories.componentMetaInfoWrapper({ componentId: 'c1', teamKey: 't1', allowEdit: true })
}

function editor(): Component {
    const component = factories.componentMetaInfoEditor({ componentId: 'c1', teamKey: '', metadata: null, contactProfiles: [] })
    component.$dispatch = mock()
    return component
}

describe('component metadata alerts', () => {
    let consoleError: ReturnType<typeof spyOn>

    beforeEach(() => {
        showError.mockClear()
        showSuccess.mockClear()
        consoleError = spyOn(console, 'error').mockImplementation(() => {})
        globals.document = { querySelector: () => ({ getAttribute: () => 'csrf' }) }
        globals.window = { dispatchEvent: () => true }
    })

    afterEach(() => {
        consoleError.mockRestore()
        for (const [name, value] of Object.entries(realGlobals)) {
            if (value === undefined) delete globals[name]
            else globals[name] = value
        }
    })

    test('a failed metadata load shows an error', async () => {
        respond(new Response('', { status: 500 }))
        await wrapper().fetchMetadata()
        expect(showError).toHaveBeenCalledWith('Failed to load component metadata')
    })

    test('a network failure while loading shows an error', async () => {
        respond(new Error('offline'))
        await wrapper().fetchMetadata()
        expect(showError).toHaveBeenCalledWith('Network error loading metadata')
    })

    test('refreshing after an update confirms it', async () => {
        respond(Response.json({}))
        wrapper().refreshDisplay()
        expect(showSuccess).toHaveBeenCalledWith('Metadata updated successfully')
    })

    test('the editor reports a failed load', async () => {
        respond(new Error('offline'))
        await editor().loadMetadata()
        expect(showError).toHaveBeenCalledWith('Failed to load component metadata')
    })

    test('the editor reports the server reason when saving fails', async () => {
        respond(Response.json({ detail: 'Supplier name is too long' }, { status: 400 }))
        await editor().updateMetaData()
        expect(showError).toHaveBeenCalledWith('Supplier name is too long')
        expect(showSuccess).not.toHaveBeenCalled()
    })

    test('the editor confirms a successful save', async () => {
        respond(Response.json({}))
        await editor().updateMetaData()
        expect(showSuccess).toHaveBeenCalledWith('Metadata saved successfully')
        expect(showError).not.toHaveBeenCalled()
    })
})
