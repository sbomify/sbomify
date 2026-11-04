import { describe, test, expect } from 'bun:test'
import { renderedByTemplates, type AlpineTemplate } from './htmx-history-snapshot'

// Stand-ins for elements: the collector only passes them through.
const el = (name: string) => ({ name }) as unknown as Element

describe('renderedByTemplates', () => {
    test('collects what x-teleport, x-if and x-for rendered', () => {
        const dialog = el('dialog')
        const shown = el('shown')
        const first = el('first')
        const second = el('second')
        const templates: AlpineTemplate[] = [
            { _x_teleport: dialog },
            { _x_currentIfEl: shown },
            { _x_lookup: new Map([['a', first], ['b', second]]) },
        ]

        expect(renderedByTemplates(templates)).toEqual([dialog, shown, first, second])
    })

    // A template Alpine has not rendered, or one whose x-if is false, has
    // nothing in the page to leave out of the snapshot.
    test('skips templates with nothing rendered', () => {
        expect(renderedByTemplates([{}, { _x_lookup: new Map() }])).toEqual([])
    })
})
