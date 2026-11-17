import { describe, test, expect, beforeEach } from 'bun:test'
import { compareVersions, rangeMatch, verdictFor, versionCheck, type VersionRange } from './version-check'

function range(overrides: Partial<VersionRange>): VersionRange {
    return { label: '', introduced: '', fixed: '', last_affected: '', ...overrides }
}

describe('compareVersions', () => {
    test('orders dotted numbers segment by segment, not as text', () => {
        expect(compareVersions('2.10.0', '2.9.0')).toBe(1)
        expect(compareVersions('2.9.0', '2.10.0')).toBe(-1)
    })

    test('treats missing segments and a leading v as equal', () => {
        expect(compareVersions('v26.7', '26.7.0')).toBe(0)
    })

    test('puts a pre-release before its release and ignores build metadata', () => {
        expect(compareVersions('1.0.0-rc1', '1.0.0')).toBe(-1)
        expect(compareVersions('1.0.0+build.5', '1.0.0')).toBe(0)
    })

    test('matches anything else only when it is the same string', () => {
        expect(compareVersions('6282ec8', '6282EC8')).toBe(0)
        expect(compareVersions('6282ec8', '1.0.0')).toBeNull()
    })
})

describe('rangeMatch', () => {
    test('a pinned version holds only itself', () => {
        const pin = range({ introduced: '26.7.0', last_affected: '26.7.0' })
        expect(rangeMatch(pin, 'v26.7.0')).toBe('in')
        expect(rangeMatch(pin, '26.7.1')).toBe('out')
    })

    test('a fixed bound excludes the fix and everything after it', () => {
        const span = range({ introduced: '1.0.0', fixed: '2.0.0' })
        expect(rangeMatch(span, '1.4.2')).toBe('in')
        expect(rangeMatch(span, '2.0.0')).toBe('out')
        expect(rangeMatch(span, '0.9.0')).toBe('out')
    })

    test('a last affected bound includes that version', () => {
        expect(rangeMatch(range({ last_affected: '1.4.2' }), '1.4.2')).toBe('in')
        expect(rangeMatch(range({ last_affected: '1.4.2' }), '1.4.3')).toBe('out')
    })

    test('a span bounded by something it cannot order says so', () => {
        expect(rangeMatch(range({ fixed: 'abc1234' }), '1.0.0')).toBe('unknown')
    })
})

describe('verdictFor', () => {
    const ranges = [range({ introduced: '26.7.0', last_affected: '26.7.0' }), range({ fixed: '25.0.0' })]

    test('is affected when any range holds the version', () => {
        expect(verdictFor({ suppressed: false, ranges }, '24.1.0')).toBe('affected')
        expect(verdictFor({ suppressed: false, ranges }, '26.7.0')).toBe('affected')
    })

    test('is not affected when every range rules it out', () => {
        expect(verdictFor({ suppressed: false, ranges }, '26.8.0')).toBe('not_affected')
    })

    test('a product that is not affected answers for every version', () => {
        expect(verdictFor({ suppressed: true, ranges: [] }, '1.0.0')).toBe('not_affected')
    })

    test('a product with no ranges yet cannot be checked', () => {
        expect(verdictFor({ suppressed: false, ranges: [] }, '1.0.0')).toBe('unknown')
    })

    test('says nothing until a version is typed', () => {
        expect(verdictFor({ suppressed: false, ranges }, '  ')).toBeNull()
    })
})

describe('versionCheck', () => {
    beforeEach(() => {
        ;(globalThis as unknown as { window: unknown }).window = {
            parseJsonScript: () => ({
                a: { suppressed: false, ranges: [range({ fixed: '2.0.0' })] },
                b: { suppressed: true, ranges: [] },
            }),
        }
    })

    test('reads its ranges from the page and answers per row', () => {
        const check = versionCheck('checks')
        check.init()
        check.query = '1.5.0'
        expect(check.verdict('a')).toBe('affected')
        expect(check.variant('a')).toBe('danger')
        expect(check.text('b')).toBe('1.5.0 is not affected')
        expect(check.match('a', 0)).toBe('in')
        expect(check.summary).toBe('1.5.0 is affected in 1 of 2 products.')
    })

    test('binds nothing while the field is empty', () => {
        const check = versionCheck('checks')
        check.init()
        expect(check.variant('a')).toBeNull()
        expect(check.match('a', 0)).toBeNull()
        expect(check.summary).toBe('')
    })
})
