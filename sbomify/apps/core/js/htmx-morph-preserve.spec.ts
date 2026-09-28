import { describe, test, expect, mock } from 'bun:test'
import { morphPreservingMarkedSubtrees } from './htmx-morph-preserve'

// No DOM library in this repo, so the nodes are the smallest shape the swap
// actually touches: a node type, hx-preserve, children and outerHTML.
const ELEMENT = 1
const FRAGMENT = 11

interface FakeNode {
    nodeType: number
    id: string
    preserve?: boolean
    children: FakeNode[]
    outerHTML: string
    hasAttribute(name: string): boolean
    firstElementChild?: FakeNode | null
}

function el(id: string, { preserve = false, children = [] as FakeNode[] } = {}): FakeNode {
    return {
        nodeType: ELEMENT,
        id,
        preserve,
        children,
        outerHTML: `<div id="${id}"></div>`,
        hasAttribute: (name: string) => name === 'hx-preserve' && preserve,
    }
}

function textNode(): FakeNode {
    return {
        nodeType: 3,
        id: '',
        children: [],
        outerHTML: '',
        hasAttribute: () => {
            throw new Error('a text node has no attributes')
        },
    }
}

/** Stands in for Alpine.morph, walking the tree the way a morph would. */
function recordingAlpine() {
    const visited: string[] = []
    const skipped: string[] = []
    const morph = mock((target: unknown, _html: unknown, options?: {
        updating: (el: unknown, toEl: unknown, childrenOnly: boolean, skip: () => void) => void
    }) => {
        if (!options) return
        const visit = (node: FakeNode) => {
            visited.push(node.id)
            let wasSkipped = false
            options.updating(node, node, false, () => {
                wasSkipped = true
            })
            if (wasSkipped) {
                skipped.push(node.id)
                return
            }
            node.children.forEach(visit)
        }
        visit(target as FakeNode)
    })
    type Alpine = Parameters<typeof morphPreservingMarkedSubtrees>[0]
    return { alpine: { morph } as unknown as Alpine, visited, skipped, morph }
}

function page(): FakeNode {
    return el('artifact-content', {
        children: [
            el('summary', { children: [el('count')] }),
            el('findings-run1', { preserve: true, children: [el('loaded-table')] }),
            el('danger'),
        ],
    })
}

const asNode = (n: FakeNode) => n as unknown as Node
const asElement = (n: FakeNode) => n as unknown as Element

describe('morph-preserve', () => {
    test('skips an hx-preserve subtree', () => {
        const { alpine, skipped } = recordingAlpine()

        morphPreservingMarkedSubtrees(alpine, asElement(page()), asNode(el('incoming')))

        expect(skipped).toEqual(['findings-run1'])
    })

    test('never descends into a preserved subtree', () => {
        // The loaded table is the thing being protected. Visiting it at all
        // would mean the morph could still replace what the reader is reading.
        const { alpine, visited } = recordingAlpine()

        morphPreservingMarkedSubtrees(alpine, asElement(page()), asNode(el('incoming')))

        expect(visited).not.toContain('loaded-table')
    })

    test('morphs everything else', () => {
        const { alpine, visited } = recordingAlpine()

        morphPreservingMarkedSubtrees(alpine, asElement(page()), asNode(el('incoming')))

        expect(visited).toEqual(['artifact-content', 'summary', 'count', 'findings-run1', 'danger'])
    })

    test('does not ask a text node for attributes', () => {
        const { alpine } = recordingAlpine()
        const root = el('artifact-content', { children: [textNode()] })

        expect(() =>
            morphPreservingMarkedSubtrees(alpine, asElement(root), asNode(el('incoming')))
        ).not.toThrow()
    })

    test('takes the first element of a fragment', () => {
        const { alpine, morph } = recordingAlpine()
        const first = el('artifact-content')
        const fragment: FakeNode = {
            nodeType: FRAGMENT,
            id: '',
            children: [first],
            outerHTML: '',
            firstElementChild: first,
            hasAttribute: () => false,
        }
        const target = page()

        const result = morphPreservingMarkedSubtrees(alpine, asElement(target), asNode(fragment))

        expect(morph.mock.calls[0]![1]).toBe(first.outerHTML)
        expect(result).toEqual([asElement(target)])
    })

    test('an empty fragment is not a swap', () => {
        const { alpine, morph } = recordingAlpine()
        const fragment: FakeNode = {
            nodeType: FRAGMENT,
            id: '',
            children: [],
            outerHTML: '',
            firstElementChild: null,
            hasAttribute: () => false,
        }

        const result = morphPreservingMarkedSubtrees(alpine, asElement(page()), asNode(fragment))

        expect(result).toBe(false)
        expect(morph).not.toHaveBeenCalled()
    })
})
