import { describe, expect, test } from 'bun:test';

import { labelTable } from './table-stack';

interface FakeCell {
    colSpan: number;
    textContent: string;
    dataset: Record<string, string>;
    attributes: Map<string, string>;
    hasAttribute(name: string): boolean;
    setAttribute(name: string, value: string): void;
}

function cell(text = '', colSpan = 1, dataset: Record<string, string> = {}): FakeCell {
    const attributes = new Map<string, string>();
    return {
        colSpan,
        textContent: text,
        dataset,
        attributes,
        hasAttribute: (name) => attributes.has(name),
        setAttribute: (name, value) => void attributes.set(name, value),
    };
}

function table(headers: FakeCell[], rows: FakeCell[][]): HTMLTableElement {
    return {
        tHead: { rows: [{ cells: headers }] },
        tBodies: [{ rows: rows.map((cells) => ({ cells })) }],
    } as unknown as HTMLTableElement;
}

describe('labelTable', () => {
    test('labels each cell with its column header', () => {
        const name = cell('Acme');
        const status = cell('Public');
        labelTable(table([cell('  Product \n'), cell('Visibility')], [[name, status]]));
        expect(name.attributes.get('data-label')).toBe('Product');
        expect(status.attributes.get('data-label')).toBe('Visibility');
    });

    test('leaves full-width cells and empty headers unlabelled', () => {
        const empty = cell('No products yet', 2);
        const actions = cell('Edit');
        labelTable(table([cell('Product'), cell('')], [[empty], [cell('Acme'), actions]]));
        expect(empty.attributes.has('data-label')).toBe(false);
        expect(actions.attributes.has('data-label')).toBe(false);
    });

    test('counts header colspans so later cells keep their column', () => {
        const last = cell('3 days');
        labelTable(table([cell('Name', 2), cell('Age')], [[cell('a'), cell('b'), last]]));
        expect(last.attributes.get('data-label')).toBe('Age');
    });

    test("keeps a label the template already set, and honours a header's own label", () => {
        const own = cell('x');
        own.attributes.set('data-label', 'Custom');
        const fromHeader = cell('y');
        labelTable(table([cell('A'), cell('Sort', 1, { label: 'Severity' })], [[own, fromHeader]]));
        expect(own.attributes.get('data-label')).toBe('Custom');
        expect(fromHeader.attributes.get('data-label')).toBe('Severity');
    });

    test('skips an empty header row a template left before the real one', () => {
        const value = cell('14 days');
        const stray = { cells: [] };
        const header = { cells: [cell('Patch SLA')] };
        labelTable({
            tHead: { rows: [stray, header] },
            tBodies: [{ rows: [{ cells: [value] }] }],
        } as unknown as HTMLTableElement);
        expect(value.attributes.get('data-label')).toBe('Patch SLA');
    });
});
