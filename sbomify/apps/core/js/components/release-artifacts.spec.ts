import { describe, test, expect, mock } from 'bun:test'

// Alpine reaches for a document the moment it is imported, so it is stubbed
// before the module under test is loaded — hence the dynamic import.
mock.module('alpinejs', () => ({
    default: { data: mock(() => undefined) }
}))

const { artifactTypeOf, artifactTypeStyle } = await import('./release-artifacts')

describe('artifactTypeOf', () => {
    test('an SBOM row is typed by its bom_type', () => {
        expect(artifactTypeOf('sbom', 'hbom')).toBe('hbom')
        expect(artifactTypeOf('sbom', 'cbom')).toBe('cbom')
        expect(artifactTypeOf('sbom', 'vex')).toBe('vex')
        expect(artifactTypeOf('sbom', 'aibom')).toBe('aibom')
    })

    test('an untagged SBOM row stays an SBOM', () => {
        expect(artifactTypeOf('sbom')).toBe('sbom')
        expect(artifactTypeOf('sbom', '')).toBe('sbom')
    })

    test('non-SBOM rows keep their artifact_type and ignore bom_type', () => {
        expect(artifactTypeOf('document')).toBe('document')
        expect(artifactTypeOf('document', 'hbom')).toBe('document')
    })

    test('a missing artifact_type is unknown', () => {
        expect(artifactTypeOf()).toBe('unknown')
    })
})

describe('artifactTypeStyle', () => {
    test('every BOM type gets its own icon', () => {
        const icons = ['sbom', 'vex', 'cbom', 'hbom', 'document'].map(t => artifactTypeStyle(t).icon)
        expect(icons).toEqual([
            'fas fa-file-code',
            'fas fa-file-contract',
            'fas fa-key',
            'fas fa-microchip',
            'fas fa-file-alt'
        ])
        expect(new Set(icons).size).toBe(icons.length)
    })

    test('an HBOM is not styled as an SBOM', () => {
        expect(artifactTypeStyle('hbom')).not.toEqual(artifactTypeStyle('sbom'))
        expect(artifactTypeStyle('cbom')).not.toEqual(artifactTypeStyle('sbom'))
    })

    test('badge and icon classes agree on the tone', () => {
        for (const type of ['sbom', 'vex', 'cbom', 'hbom', 'document']) {
            const style = artifactTypeStyle(type)
            expect(style.badgeClass.startsWith(style.iconClass)).toBe(true)
        }
    })

    test('unmapped, empty and missing types fall back to the neutral style', () => {
        const fallback = { icon: 'fas fa-file', iconClass: 'bg-surface text-text-muted', badgeClass: 'bg-surface text-text-muted border border-border' }
        expect(artifactTypeStyle('obom')).toEqual(fallback)
        expect(artifactTypeStyle('')).toEqual(fallback)
        expect(artifactTypeStyle()).toEqual(fallback)
    })

    test('lookup is case-insensitive', () => {
        expect(artifactTypeStyle('HBOM')).toEqual(artifactTypeStyle('hbom'))
    })
})
