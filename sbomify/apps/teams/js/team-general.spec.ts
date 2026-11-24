import { describe, test, expect, mock, beforeEach } from 'bun:test'

type AlpineFactory = (initial?: Record<string, string>) => DirtyForm

interface DirtyForm {
    original: Record<string, string>
    fields: Record<string, string>
    hasUnsavedChanges(): boolean
    discard(): void
}

const registered = new Map<string, AlpineFactory>()
const mockAlpineData = mock((name: string, callback: AlpineFactory) => {
    registered.set(name, callback)
})

mock.module('alpinejs', () => ({
    default: {
        data: mockAlpineData
    }
}))

const { registerTeamGeneral } = await import('./team-general')

/** The component as the templates get it, through the real registration. */
function build(initial?: Record<string, string>): DirtyForm {
    registered.clear()
    registerTeamGeneral()
    const factory = registered.get('dirtySettingsForm')
    if (!factory) throw new Error('dirtySettingsForm was never registered')
    return factory(initial)
}

describe('dirtySettingsForm', () => {
    beforeEach(() => {
        mockAlpineData.mockClear()
    })

    test('registers under the name all three settings forms bind to', () => {
        build({})
        expect(registered.has('dirtySettingsForm')).toBe(true)
    })

    test('an untouched form is not dirty, whatever it holds', () => {
        const form = build({ name: 'My Workspace', sbom_freshness_days: '45' })

        expect(form.hasUnsavedChanges()).toBe(false)
    })

    test('a change to any one field makes the form dirty', () => {
        const form = build({ mode: 'custom', critical: '7', high: '30' })

        form.fields.high = '14'

        expect(form.hasUnsavedChanges()).toBe(true)
    })

    test('discard puts every field back and clears the dirty state', () => {
        const form = build({ name: 'Before', sbom_freshness_days: '45' })

        form.fields.name = 'After'
        form.fields.sbom_freshness_days = ''
        expect(form.hasUnsavedChanges()).toBe(true)

        form.discard()

        expect(form.fields).toEqual({ name: 'Before', sbom_freshness_days: '45' })
        expect(form.hasUnsavedChanges()).toBe(false)
    })

    test('editing back to the starting value is not a change', () => {
        const form = build({ name: 'Original' })

        form.fields.name = 'Changed'
        form.fields.name = 'Original'

        expect(form.hasUnsavedChanges()).toBe(false)
    })

    test('an emptied field and an unset one are the same value', () => {
        // '' means no policy and '0' is a window that expires immediately, so
        // the two must not collapse into each other.
        const form = build({ sbom_freshness_days: '' })

        form.fields.sbom_freshness_days = '0'
        expect(form.hasUnsavedChanges()).toBe(true)

        form.fields.sbom_freshness_days = ''
        expect(form.hasUnsavedChanges()).toBe(false)
    })

    test('whitespace is a change, because the server will store it', () => {
        const form = build({ name: 'Test' })

        form.fields.name = 'Test '

        expect(form.hasUnsavedChanges()).toBe(true)
    })

    test('discard does not alias the starting values', () => {
        const form = build({ name: 'Original' })

        form.discard()
        form.fields.name = 'Changed'

        expect(form.original.name).toBe('Original')
    })

    test('a form with no fields is never dirty', () => {
        const form = build()

        expect(form.hasUnsavedChanges()).toBe(false)
    })
})
