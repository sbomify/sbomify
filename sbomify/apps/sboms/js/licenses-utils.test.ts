import { describe, it, expect } from 'bun:test';
import { getFilteredLicenses, tokenize, type LicenseInfo } from './licenses-utils';

const mockLicenses: LicenseInfo[] = [
    { key: 'Apache-2.0', name: 'Apache License 2.0', category: 'permissive' },
    { key: 'MIT', name: 'MIT License', category: 'permissive' },
    { key: 'Commons-Clause', name: 'Commons Clause', category: 'proprietary' },
    { key: 'GPL-3.0', name: 'GNU General Public License v3.0', category: 'copyleft' }
];

describe('Tokenizer', () => {
    it('tokenizes simple expression', () => {
        const tokens = tokenize('Apache-2.0');
        expect(tokens).toEqual([
            { type: 'IDENTIFIER', value: 'Apache-2.0', start: 0, end: 10 }
        ]);
    });

    it('tokenizes multiple identifiers', () => {
        const tokens = tokenize('Apache-2.0 OR MIT');
        expect(tokens).toEqual([
            { type: 'IDENTIFIER', value: 'Apache-2.0', start: 0, end: 10 },
            { type: 'IDENTIFIER', value: 'OR', start: 11, end: 13 },
            { type: 'IDENTIFIER', value: 'MIT', start: 14, end: 17 }
        ]);
    });

    it('tokenizes parentheses', () => {
        const tokens = tokenize('(MIT OR)');
        expect(tokens).toEqual([
            { type: 'PAREN', value: '(', start: 0, end: 1 },
            { type: 'IDENTIFIER', value: 'MIT', start: 1, end: 4 },
            { type: 'IDENTIFIER', value: 'OR', start: 5, end: 7 },
            { type: 'PAREN', value: ')', start: 7, end: 8 }
        ]);
    });

    it('handles extra whitespace', () => {
        const tokens = tokenize('  MIT   OR  ');
        expect(tokens).toEqual([
            { type: 'IDENTIFIER', value: 'MIT', start: 2, end: 5 },
            { type: 'IDENTIFIER', value: 'OR', start: 8, end: 10 }
        ]);
    });
});

describe('getFilteredLicenses (Tokenizer Strategy)', () => {
    it('returns all licenses when expression is empty', () => {
        const result = getFilteredLicenses('', mockLicenses);
        expect(result).toHaveLength(mockLicenses.length);
    });

    it('filters by matching license key start', () => {
        const result = getFilteredLicenses('Apa', mockLicenses);
        expect(result).toHaveLength(1);
        expect(result[0].key).toBe('Apache-2.0');
    });

    it('suggests operators after a valid license', () => {
        const result = getFilteredLicenses('Apache-2.0 ', mockLicenses);
        // Should suggest operators since we finished a license
        const operators = result.filter(r => r.category === 'operator');
        expect(operators.length).toBeGreaterThan(0);
        expect(operators.some(o => o.key === 'AND')).toBe(true);
    });

    it('suggests licenses after an operator', () => {
        const result = getFilteredLicenses('Apache-2.0 OR ', mockLicenses);
        // Should suggest licenses
        const licenses = result.filter(r => r.category !== 'operator');
        expect(licenses.length).toBeGreaterThan(0);
        expect(licenses.some(l => l.key === 'MIT')).toBe(true);
    });

    it('suggests licenses after open paren', () => {
        const result = getFilteredLicenses('(', mockLicenses);
        const licenses = result.filter(r => r.category !== 'operator');
        expect(licenses.length).toBeGreaterThan(0);
    });

    it('handles "WITH" exception suggestion', () => {
        // "Apache-2.0 WI" -> should suggest WITH
        const result = getFilteredLicenses('Apache-2.0 WI', mockLicenses);
        const wOp = result.find(r => r.key === 'WITH');
        expect(wOp).toBeDefined();
    });

    it('handles partial matching of second license in expression', () => {
        const result = getFilteredLicenses('Apache-2.0 OR Com', mockLicenses);
        expect(result).toHaveLength(1);
        expect(result[0].key).toBe('Commons-Clause');
    });

    it('handles nested parentheses context', () => {
        const result = getFilteredLicenses('(MIT OR (Apache-2.0 AND Com', mockLicenses);
        expect(result).toHaveLength(1);
        expect(result[0].key).toBe('Commons-Clause');
    });
});
