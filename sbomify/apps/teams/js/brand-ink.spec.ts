import { describe, test, expect } from 'bun:test'
import { brandFill, inkOnColor } from './brand-ink'

// The expected values come from sbomify/apps/teams/branding.py. If one side
// changes, this fails rather than the preview quietly lying about the ink.
describe('brandFill', () => {
    test('keeps a valid hex', () => {
        expect(brandFill('#ffd400')).toBe('#ffd400')
        expect(brandFill('  #FFD400  ')).toBe('#FFD400')
    })

    test('falls back to the platform accent', () => {
        expect(brandFill('not a colour')).toBe('#4263EB')
        expect(brandFill('')).toBe('#4263EB')
        expect(brandFill(null)).toBe('#4263EB')
    })
})

describe('inkOnColor', () => {
    test('white on a dark brand', () => {
        expect(inkOnColor('#000000')).toBe('#ffffff')
        expect(inkOnColor('#25293F')).toBe('#ffffff')
        expect(inkOnColor('#4263EB')).toBe('#ffffff')
    })

    test('platform ink on a light brand', () => {
        expect(inkOnColor('#ffffff')).toBe('#25293F')
        expect(inkOnColor('#ffd400')).toBe('#25293F')
        expect(inkOnColor('#767676')).toBe('#25293F')
    })
})
