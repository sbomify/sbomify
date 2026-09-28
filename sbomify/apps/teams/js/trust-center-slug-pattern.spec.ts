import { describe, expect, test } from 'bun:test'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

// Browsers compile an input's pattern as ^(?:pattern)$ with the v flag. One that
// fails to compile is skipped, so the field would accept anything.
const template = readFileSync(
    join(import.meta.dir, '../templates/teams/team_settings_tabs/trust_center.html.j2'),
    'utf8'
)
const input = template.match(/<c-forms\.input\b[^>]*\bid="slug"[^>]*>/)?.[0] ?? ''
const attr = (name: string) => input.match(new RegExp(`\\s${name}="([^"]*)"`))?.[1] ?? ''
const pattern = attr('pattern')
const compile = () => new RegExp(`^(?:${pattern})$`, 'v')

describe('Trust Center slug pattern', () => {
    test('compiles under the v flag', () => {
        expect(pattern).not.toBe('')
        expect(compile).not.toThrow()
    })

    // The pattern carries the format only; the length bounds are separate attributes.
    test('bounds the length as the Team.slug field does', () => {
        expect(attr('minlength')).toBe('3')
        expect(attr('maxlength')).toBe('63')
    })

    test.each(['abc', 'a-b', 'a1-2b', 'abc---def', '123', 'a'.repeat(63)])('accepts %p, as the Team.slug validator does', (slug) => {
        expect(compile().test(slug)).toBe(true)
    })

    test.each(['-abc', 'abc-', 'ABC', 'a_b', 'a.b', 'a b'])('refuses %p, as the Team.slug validator does', (slug) => {
        expect(compile().test(slug)).toBe(false)
    })
})
