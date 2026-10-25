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
