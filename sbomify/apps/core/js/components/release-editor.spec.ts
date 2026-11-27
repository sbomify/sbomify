import { describe, test, expect, mock, spyOn, beforeEach, afterEach } from 'bun:test'

const showSuccess = mock<(message: string) => void>()
const showError = mock<(message: string) => void>()

mock.module('../alerts', () => ({
    showSuccess,
    showError,
    showWarning: mock(),
    showInfo: mock(),
    showToast: mock(),
    showConfirmation: mock(),
}))

mock.module('../csrf', () => ({ getCsrfToken: () => 'csrf-value' }))

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Editor = Record<string, any>
let releaseEditor: (params: Record<string, unknown>) => Editor

mock.module('alpinejs', () => ({
    default: {
        data: (_name: string, factory: typeof releaseEditor) => {
            releaseEditor = factory
        },
    },
}))

const { registerReleaseEditor } = await import('./release-editor')
registerReleaseEditor()

const globals = globalThis as unknown as Record<string, unknown>
const realGlobals = { fetch: globals.fetch, window: globals.window }
const release = { id: 'r1', name: 'Spring', version: '1.0', is_prerelease: false, is_latest: false, created_at: '2026-01-01T10:00:00Z' }

function editor(): Editor {
    const component = releaseEditor({ refreshEvent: 'refresh-releases', canDelete: true })
    component.$dispatch = mock()
    return component
}

describe('release editor requests', () => {
    let consoleError: ReturnType<typeof spyOn>

    beforeEach(() => {
        showSuccess.mockClear()
        showError.mockClear()
        consoleError = spyOn(console, 'error').mockImplementation(() => {})
        globals.window = { dispatchEvent: () => true }
    })

    afterEach(() => {
        consoleError.mockRestore()
        for (const [name, value] of Object.entries(realGlobals)) {
            if (value === undefined) delete globals[name]
            else globals[name] = value
        }
    })

    test('saving sends a PATCH with the CSRF token and refreshes the table', async () => {
        const fetcher = mock(async () => Response.json({}))
        globals.fetch = fetcher
        const component = editor()
        component.openEditModal(release)

        await component.submitRelease()

        const [url, init] = fetcher.mock.calls[0] as unknown as [string, RequestInit]
        expect(url).toBe('/api/v1/releases/r1')
        expect(init.method).toBe('PATCH')
        expect(init.headers).toEqual({ 'Content-Type': 'application/json', 'X-CSRFToken': 'csrf-value' })
        expect(JSON.parse(String(init.body))).toMatchObject({ name: 'Spring', version: '1.0', is_prerelease: false })
        expect(showSuccess).toHaveBeenCalledWith('Release updated')
        expect(component.$dispatch).toHaveBeenCalledWith('refresh-releases')
        expect(component.saving).toBe(false)
    })

    test('a refused save shows the server reason and keeps the modal open', async () => {
        globals.fetch = mock(async () => Response.json({ detail: 'That version already exists' }, { status: 409 }))
        const component = editor()
        component.openEditModal(release)

        await component.submitRelease()

        expect(showError).toHaveBeenCalledWith('That version already exists')
        expect(showSuccess).not.toHaveBeenCalled()
        expect(component.showModal).toBe(true)
        expect(component.saving).toBe(false)
    })

    test('a refused delete says so', async () => {
        const fetcher = mock(async () => new Response('', { status: 403 }))
        globals.fetch = fetcher
        const component = editor()
        component.openDeleteModal(release)

        await component.confirmDeleteRelease()

        expect(fetcher).toHaveBeenCalledWith('/api/v1/releases/r1', { method: 'DELETE', headers: { 'X-CSRFToken': 'csrf-value' } })
        expect(showError).toHaveBeenCalledWith('Failed to delete release')
        expect(showSuccess).not.toHaveBeenCalled()
    })
})

interface ReplaceData {
    options: { id: string; name: string }[]
    replaces: Record<string, { id: string; name: string; drop_in: boolean }[]>
}

// 2.0 replaces 1.9.5 on the same line, so 1.9.5 is not among the monitored options.
const replaceData: ReplaceData = {
    options: [{ id: 'rel-1', name: '2.0' }, { id: 'rel-0', name: '1.8' }],
    replaces: { 'rel-1': [{ id: 'rel-old', name: '1.9.5', drop_in: true }] },
}

const dated = {
    id: 'rel-1',
    name: '2.0',
    version: '2.0',
    is_prerelease: false,
    is_latest: false,
    created_at: '2025-01-01T00:00:00Z',
    release_date: '2025-03-01T12:00:45.500Z',
}

/** Builds the real Alpine component and opens the dialog on the release above. */
function open(data?: ReplaceData): Editor {
    const component = releaseEditor({ refreshEvent: 'refresh-releases', replaceData: data })
    component.$dispatch = mock()
    component.openEditModal(dated)
    return component
}

describe('release editor', () => {
    let fetcher: ReturnType<typeof mock>

    /** The JSON body of the first request the editor sent. */
    function sent(): Record<string, unknown> {
        const [, init] = fetcher.mock.calls[0] as unknown as [string, RequestInit]
        return JSON.parse(String(init.body))
    }

    beforeEach(() => {
        showError.mockClear()
        fetcher = mock(async () => Response.json({}))
        globals.fetch = fetcher
        globals.window = { dispatchEvent: () => true }
    })

    afterEach(() => {
        for (const [name, value] of Object.entries(realGlobals)) {
            if (value === undefined) delete globals[name]
            else globals[name] = value
        }
    })

    test('an edit that leaves the release date alone does not send it', async () => {
        const editor = open()
        editor.form.name = '2.0 LTS'

        await editor.submitRelease()

        const [url] = fetcher.mock.calls[0] as unknown as [string]
        expect(url).toBe('/api/v1/releases/rel-1')
        expect(sent().name).toBe('2.0 LTS')
        expect(sent()).not.toHaveProperty('released_at')
    })

    test('a release date the user changed is sent', async () => {
        const editor = open()
        editor.form.released_at = '2025-04-01T09:30'

        await editor.submitRelease()

        expect(sent().released_at).toBe(new Date('2025-04-01T09:30').toISOString())
    })

    test('the dialog opens on the release it replaces and offers it back', () => {
        const editor = open(replaceData)

        expect(editor.form.replaces).toBe('rel-old')
        expect(editor.form.replaces_line).toBe('same')
        expect(editor.replaceOptions()).toEqual([{ id: 'rel-old', name: '1.9.5' }, { id: 'rel-0', name: '1.8' }])
    })

    test('an edit that leaves the link alone does not send it', async () => {
        const editor = open(replaceData)
        editor.form.name = '2.0 LTS'

        await editor.submitRelease()

        expect(sent()).not.toHaveProperty('supersedes')
    })

    test('choosing None detaches the release', async () => {
        const editor = open(replaceData)
        editor.form.replaces = ''

        await editor.submitRelease()

        expect(sent().supersedes).toEqual([])
    })

    test('moving the link to a new line keeps the old release monitored', async () => {
        const editor = open(replaceData)
        editor.form.replaces_line = 'new'

        await editor.submitRelease()

        expect(sent().supersedes).toEqual([{ release_id: 'rel-old', drop_in: false }])
    })

    test('a release chosen without a line is not saved', async () => {
        const editor = open({ ...replaceData, replaces: {} })
        editor.form.replaces = 'rel-0'

        await editor.submitRelease()

        expect(fetcher).not.toHaveBeenCalled()
        expect(showError.mock.calls[0]![0]).toContain('Same line or New line')
    })

    test('a release that replaces several is left to its own page', async () => {
        const editor = open({
            ...replaceData,
            replaces: { 'rel-1': [{ id: 'a', name: '1.9', drop_in: true }, { id: 'b', name: '1.8', drop_in: false }] },
        })
        expect(editor.replacesLocked).toBe(true)
        editor.form.name = '2.0 LTS'

        await editor.submitRelease()

        expect(sent()).not.toHaveProperty('supersedes')
    })
})
