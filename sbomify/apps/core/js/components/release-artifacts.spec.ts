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
type Artifacts = Record<string, any>
let releaseArtifacts: (params: Record<string, unknown>) => Artifacts

mock.module('alpinejs', () => ({
    default: {
        data: (_name: string, factory: typeof releaseArtifacts) => {
            releaseArtifacts = factory
        },
    },
}))

const { registerReleaseArtifacts } = await import('./release-artifacts')
registerReleaseArtifacts()

const globals = globalThis as unknown as Record<string, unknown>
const realGlobals = { fetch: globals.fetch }

function artifacts(): Artifacts {
    return releaseArtifacts({ releaseId: 'rel1', productId: 'p1', initialArtifacts: [], routes: {} })
}

describe('release artifact requests', () => {
    let consoleError: ReturnType<typeof spyOn>

    beforeEach(() => {
        showSuccess.mockClear()
        showError.mockClear()
        consoleError = spyOn(console, 'error').mockImplementation(() => {})
    })

    afterEach(() => {
        consoleError.mockRestore()
        for (const [name, value] of Object.entries(realGlobals)) {
            if (value === undefined) delete globals[name]
            else globals[name] = value
        }
    })

    test('loading accepts a paginated body', async () => {
        const fetcher = mock(async () => Response.json({ items: [{ id: 'a1' }] }))
        globals.fetch = fetcher
        const component = artifacts()

        await component.loadArtifacts()

        expect(fetcher).toHaveBeenCalledWith('/api/v1/releases/rel1/artifacts?mode=existing&page_size=-1')
        expect(component.artifacts).toEqual([{ id: 'a1' }])
    })

    test('a failed load says so', async () => {
        globals.fetch = mock(async () => new Response('', { status: 500 }))
        const component = artifacts()

        await component.loadArtifacts()

        expect(showError).toHaveBeenCalledWith('Failed to load artifacts')
        expect(component.isLoading).toBe(false)
    })

    test('adding posts each artifact and reports the refusals', async () => {
        const posts: RequestInit[] = []
        globals.fetch = mock(async (_url: string, init?: RequestInit) => {
            if (init?.method !== 'POST') return Response.json([])
            posts.push(init)
            return 'sbom_id' in JSON.parse(String(init.body))
                ? Response.json({}, { status: 201 })
                : Response.json({ detail: 'Already in this release' }, { status: 409 })
        })
        const component = artifacts()
        component.availableArtifacts = [
            { id: 's1', artifact_type: 'sbom', name: 'App SBOM', created_at: '' },
            { id: 'd1', artifact_type: 'document', name: 'Manual', created_at: '' },
        ]
        component.selectedArtifacts = new Set(['s1', 'd1'])

        await component.addSelectedArtifacts()

        expect(posts.map(init => JSON.parse(String(init.body)))).toEqual([{ sbom_id: 's1' }, { document_id: 'd1' }])
        expect(posts[0].headers).toEqual({ 'Content-Type': 'application/json', 'X-CSRFToken': 'csrf-value' })
        expect(showSuccess).toHaveBeenCalledWith('1 artifact(s) added to release')
        expect(showError).toHaveBeenCalledWith('Failed to add some artifacts:\nManual: Already in this release')
    })

    test('a refused removal says so', async () => {
        const fetcher = mock(async () => new Response('', { status: 404 }))
        globals.fetch = fetcher
        const component = artifacts()
        component.deleteTarget = { id: 'ra1' }

        await component.confirmRemoveArtifact()

        expect(fetcher).toHaveBeenCalledWith('/api/v1/releases/rel1/artifacts/ra1', {
            method: 'DELETE',
            headers: { 'X-CSRFToken': 'csrf-value' },
        })
        expect(showError).toHaveBeenCalledWith('Failed to remove artifact')
        expect(showSuccess).not.toHaveBeenCalled()
    })
})
