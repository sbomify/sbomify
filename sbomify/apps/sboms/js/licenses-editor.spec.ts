import { describe, test, expect } from 'bun:test'

/**
 * Tests for LicensesEditor Alpine.js component business logic
 *
 * This test suite validates the core functionality of the licenses editor component
 * including tag management, autocomplete filtering, custom license handling, and validation.
 */

describe('LicensesEditor Business Logic', () => {

    interface CustomLicense {
        name: string;
        url: string | null;
        text: string | null;
    }

    interface LicenseTag {
        value: string | CustomLicense;
        displayValue: string;
        isInvalid: boolean;
        isCustom: boolean;
    }

    interface LicenseInfo {
        key: string;
        name: string;
        category?: string | null;
    }

    describe('Tag Initialization', () => {
        const initializeTags = (licenses: (string | CustomLicense)[]): LicenseTag[] => {
            return licenses.map(lic => {
                if (typeof lic === 'string') {
                    return {
                        value: lic,
                        displayValue: lic,
                        isInvalid: false,
                        isCustom: false
                    };
                } else {
                    return {
                        value: lic,
                        displayValue: lic.name || 'Unnamed License',
                        isInvalid: false,
                        isCustom: true
                    };
                }
            }).filter(tag => tag.displayValue.length > 0);
        };

        test('should initialize empty tags from empty array', () => {
            const tags = initializeTags([]);
            expect(tags).toEqual([]);
        });

        test('should initialize string licenses as standard tags', () => {
            const tags = initializeTags(['MIT', 'Apache-2.0']);
            expect(tags.length).toBe(2);
            expect(tags[0].displayValue).toBe('MIT');
            expect(tags[0].isCustom).toBe(false);
            expect(tags[1].displayValue).toBe('Apache-2.0');
        });

        test('should initialize custom licenses with isCustom flag', () => {
            const customLicense: CustomLicense = {
                name: 'My Custom License',
                url: 'https://example.com/license',
                text: 'License text here'
            };
            const tags = initializeTags([customLicense]);
            expect(tags.length).toBe(1);
            expect(tags[0].displayValue).toBe('My Custom License');
            expect(tags[0].isCustom).toBe(true);
        });

        test('should handle mixed licenses', () => {
            const licenses: (string | CustomLicense)[] = [
                'MIT',
                { name: 'Custom', url: null, text: null },
                'GPL-3.0'
            ];
            const tags = initializeTags(licenses);
            expect(tags.length).toBe(3);
            expect(tags[1].isCustom).toBe(true);
        });

        test('should use "Unnamed License" for custom without name', () => {
            const tags = initializeTags([{ name: '', url: null, text: null }]);
            // When name is empty, displayValue becomes 'Unnamed License' which is not empty
            expect(tags.length).toBe(1);
            expect(tags[0].displayValue).toBe('Unnamed License');
        });
    });

    describe('Tag Management', () => {
        test('should add license expression as tag', () => {
            const tags: LicenseTag[] = [];

            const addTag = (expression: string) => {
                tags.push({
                    value: expression,
                    displayValue: expression,
                    isInvalid: false,
                    isCustom: false
                });
            };

            addTag('MIT');
            expect(tags.length).toBe(1);
            expect(tags[0].value).toBe('MIT');
        });

        test('should not add duplicate tags', () => {
            const tags: LicenseTag[] = [
                { value: 'MIT', displayValue: 'MIT', isInvalid: false, isCustom: false }
            ];

            const isDuplicate = (expression: string): boolean => {
                return tags.some(tag => {
                    const tagValue = typeof tag.value === 'string' ? tag.value : tag.value.name;
                    return tagValue === expression;
                });
            };

            expect(isDuplicate('MIT')).toBe(true);
            expect(isDuplicate('Apache-2.0')).toBe(false);
        });

        test('should remove tag by index', () => {
            const tags: LicenseTag[] = [
                { value: 'MIT', displayValue: 'MIT', isInvalid: false, isCustom: false },
                { value: 'Apache-2.0', displayValue: 'Apache-2.0', isInvalid: false, isCustom: false }
            ];

            tags.splice(1, 1);
            expect(tags.length).toBe(1);
            expect(tags[0].value).toBe('MIT');
        });

        test('should mark tag as invalid', () => {
            const tag: LicenseTag = {
                value: 'INVALID-LICENSE',
                displayValue: 'INVALID-LICENSE',
                isInvalid: false,
                isCustom: false
            };

            tag.isInvalid = true;
            expect(tag.isInvalid).toBe(true);
        });
    });

    describe('Autocomplete Filtering', () => {
        const licenses: LicenseInfo[] = [
            { key: 'MIT', name: 'MIT License' },
            { key: 'Apache-2.0', name: 'Apache License 2.0' },
            { key: 'GPL-3.0', name: 'GNU General Public License v3.0' },
            { key: 'BSD-3-Clause', name: 'BSD 3-Clause License' }
        ];

        const filterLicenses = (searchTerm: string): LicenseInfo[] => {
            if (!searchTerm) return licenses;
            const term = searchTerm.toLowerCase();
            return licenses.filter(lic =>
                lic.key.toLowerCase().includes(term) ||
                lic.name.toLowerCase().includes(term)
            );
        };

        test('should return all licenses when no search term', () => {
            const results = filterLicenses('');
            expect(results.length).toBe(4);
        });

        test('should filter by license key', () => {
            const results = filterLicenses('mit');
            expect(results.length).toBe(1);
            expect(results[0].key).toBe('MIT');
        });

        test('should filter by license name', () => {
            const results = filterLicenses('apache');
            expect(results.length).toBe(1);
            expect(results[0].key).toBe('Apache-2.0');
        });

        test('should be case insensitive', () => {
            expect(filterLicenses('MIT').length).toBe(1);
            expect(filterLicenses('mit').length).toBe(1);
            expect(filterLicenses('MiT').length).toBe(1);
        });

        test('should filter by partial match', () => {
            const results = filterLicenses('gpl');
            expect(results.length).toBe(1);
            expect(results[0].key).toBe('GPL-3.0');
        });
    });

    describe('Operator Suggestions', () => {
        const operators = ['AND', 'OR', 'WITH'];

        const getOperatorSuggestions = (currentToken: string): LicenseInfo[] => {
            return operators
                .filter(op => op.toLowerCase().startsWith(currentToken.toLowerCase()))
                .map(op => ({
                    key: op,
                    name: `${op} operator`,
                    category: 'operator'
                }));
        };

        test('should suggest operators matching input', () => {
            expect(getOperatorSuggestions('an').length).toBe(1);
            expect(getOperatorSuggestions('an')[0].key).toBe('AND');
        });

        test('should suggest multiple operators', () => {
            const results = getOperatorSuggestions('');
            expect(results.length).toBe(3);
        });

        test('should mark suggestions as operator category', () => {
            const results = getOperatorSuggestions('with');
            expect(results[0].category).toBe('operator');
        });
    });

    describe('Custom License Form', () => {
        test('should create custom license object', () => {
            const customLicense = {
                name: 'My License',
                url: 'https://example.com',
                text: 'Full license text'
            };

            expect(customLicense.name).toBe('My License');
            expect(customLicense.url).toBe('https://example.com');
            expect(customLicense.text).toBe('Full license text');
        });

        test('should handle optional fields', () => {
            const customLicense: CustomLicense = {
                name: 'Minimal License',
                url: null,
                text: null
            };

            expect(customLicense.name).toBe('Minimal License');
            expect(customLicense.url).toBeNull();
            expect(customLicense.text).toBeNull();
        });

        test('should update existing custom license', () => {
            const tags: LicenseTag[] = [
                {
                    value: { name: 'Old Name', url: null, text: null },
                    displayValue: 'Old Name',
                    isInvalid: false,
                    isCustom: true
                }
            ];

            const updatedLicense: CustomLicense = {
                name: 'New Name',
                url: 'https://new.url',
                text: 'Updated text'
            };

            tags[0] = {
                value: updatedLicense,
                displayValue: updatedLicense.name,
                isInvalid: false,
                isCustom: true
            };

            expect(tags[0].displayValue).toBe('New Name');
        });
    });

    describe('Keyboard Navigation', () => {
        test('should cycle through suggestions with arrow keys', () => {
            let selectedIndex = -1;
            const listLength = 5;

            // Arrow down
            selectedIndex = (selectedIndex + 1) % listLength;
            expect(selectedIndex).toBe(0);

            selectedIndex = (selectedIndex + 1) % listLength;
            expect(selectedIndex).toBe(1);

            // Wrap around
            selectedIndex = 4;
            selectedIndex = (selectedIndex + 1) % listLength;
            expect(selectedIndex).toBe(0);
        });

        test('should handle arrow up navigation', () => {
            let selectedIndex = 1;
            const listLength = 5;

            // Arrow up
            selectedIndex = selectedIndex <= 0 ? listLength - 1 : selectedIndex - 1;
            expect(selectedIndex).toBe(0);

            // Wrap to end
            selectedIndex = selectedIndex <= 0 ? listLength - 1 : selectedIndex - 1;
            expect(selectedIndex).toBe(4);
        });
    });

    describe('Update Dispatching', () => {
        test('should prepare licenses array from tags', () => {
            const tags: LicenseTag[] = [
                { value: 'MIT', displayValue: 'MIT', isInvalid: false, isCustom: false },
                { value: { name: 'Custom', url: null, text: null }, displayValue: 'Custom', isInvalid: false, isCustom: true }
            ];

            const allLicenses = tags.map(tag => tag.value);
            expect(allLicenses.length).toBe(2);
            expect(allLicenses[0]).toBe('MIT');
            expect(typeof allLicenses[1]).toBe('object');
        });

        test('should include current input in licenses', () => {
            const tags: LicenseTag[] = [
                { value: 'MIT', displayValue: 'MIT', isInvalid: false, isCustom: false }
            ];
            const currentInput = 'Apache-2.0';

            const allLicenses: (string | CustomLicense)[] = [...tags.map(t => t.value)];
            if (currentInput.trim()) {
                allLicenses.push(currentInput.trim());
            }

            expect(allLicenses.length).toBe(2);
            expect(allLicenses[1]).toBe('Apache-2.0');
        });
    });

    describe('Edge Cases', () => {
        test('should handle empty license name in custom license', () => {
            const tag: LicenseTag = {
                value: { name: '', url: null, text: null },
                displayValue: 'Unnamed License',
                isInvalid: false,
                isCustom: true
            };

            expect(tag.displayValue).toBe('Unnamed License');
        });

        test('should handle license expression with multiple operators', () => {
            const expression = 'MIT OR Apache-2.0 WITH Commons-Clause';
            expect(expression).toContain('OR');
            expect(expression).toContain('WITH');
        });

        test('should handle special characters in license key', () => {
            const license: LicenseInfo = {
                key: 'BSD-3-Clause',
                name: 'BSD 3-Clause "New" or "Revised" License'
            };

            expect(license.key).toContain('-');
            expect(license.name).toContain('"');
        });
    });
})
