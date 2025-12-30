import { describe, it, expect } from 'bun:test';

interface LicenseInfo {
    key: string;
    name: string;
    category?: string;
}

// Pure function to be extracted and tested
function parseLicenseExpression(expression: string, licenses: LicenseInfo[]): LicenseInfo[] {
    if (!expression) return licenses.slice(0, 20);

    const searchTerm = expression.toLowerCase().replace(/\s+/g, '-');
    const operators = ['AND', 'OR', 'WITH'];
    const beforeCursor = expression;
    const operatorPattern = /\s+(AND|OR|WITH)\s+/gi;

    let currentToken = beforeCursor;
    let lastOperatorEnd = 0;
    let match: RegExpExecArray | null;

    while ((match = operatorPattern.exec(beforeCursor)) !== null) {
        lastOperatorEnd = match.index + match[0].length;
    }

    if (lastOperatorEnd > 0) {
        currentToken = beforeCursor.substring(lastOperatorEnd).trim();
    }

    const combinedSuggestions: LicenseInfo[] = [...licenses];

    if (lastOperatorEnd > 0 || (beforeCursor.trim().length > 0 && !currentToken.includes(' '))) {
        operators.forEach(op => {
            if (op.toLowerCase().startsWith(currentToken.toLowerCase())) {
                combinedSuggestions.push({
                    key: op,
                    name: `${op} operator`,
                    category: 'operator'
                });
            }
        });
    }

    return combinedSuggestions.filter(item => {
        if (item.category === 'operator') {
            return item.key.toLowerCase().startsWith(currentToken.toLowerCase());
        }
        const licenseKey = item.key.toLowerCase();
        const licenseName = item.name.toLowerCase();
        return licenseKey.includes(searchTerm) || licenseName.includes(searchTerm);
    }).slice(0, 20);
}

describe('parseLicenseExpression', () => {
    const mockLicenses = [
        { key: 'MIT', name: 'MIT License' },
        { key: 'Apache-2.0', name: 'Apache License 2.0' },
        { key: 'GPL-3.0', name: 'GNU General Public License v3.0' }
    ];

    it('should return all licenses when expression is empty', () => {
        const result = parseLicenseExpression('', mockLicenses);
        expect(result).toHaveLength(3);
    });

    it('should filter licenses by name', () => {
        const result = parseLicenseExpression('MIT', mockLicenses);
        expect(result).toHaveLength(1);
        expect(result[0].key).toBe('MIT');
    });

    it('should suggest operators when applicable', () => {
        const result = parseLicenseExpression('Apache', mockLicenses);
        const apache = result.find(r => r.key === 'Apache-2.0');
        expect(apache).toBeDefined();
    });
});
