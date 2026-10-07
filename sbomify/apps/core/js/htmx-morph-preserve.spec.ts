import { describe, test, expect, mock } from 'bun:test'
import { morphPreservingMarkedSubtrees } from './htmx-morph-preserve'

// No DOM library in this repo, so the nodes are the smallest shape the swap
// actually touches: a node type, hx-preserve, children and outerHTML.
// outerHTML is a label naming the node, not markup: the swap only hands it to
// the morph, so the tests compare it and never parse it.
const ELEMENT = 1
const FRAGMENT = 11

interface FakeNode {
    nodeType: number
    id: string
    preserve?: boolean
    children: FakeNode[]
    outerHTML: string
    hasAttribute(name: string): boolean
    querySelectorAll?(selector: string): FakeNode[]
    firstElementChild?: FakeNode | null
}

function el(id: string, { preserve = false, children = [] as FakeNode[] } = {}): FakeNode {
    return {
        nodeType: ELEMENT,
        id,
        preserve,
        children,
        outerHTML: 'markup of ' + id,
        hasAttribute: (name: string) => name === 'hx-preserve' && preserve,
        querySelectorAll: (selector: string) => {
            expect(selector).toBe('[hx-preserve][id]')
            const found: FakeNode[] = []
            const walk = (n: FakeNode) => n.children.forEach((child) => {
                if (child.preserve && child.id) found.push(child)
                walk(child)
            })
            walk({ children } as FakeNode)
            return found
        },
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

const asNode = (n: FakeNode | TreeNode) => n as unknown as Node
const asElement = (n: FakeNode | TreeNode) => n as unknown as Element

/** A node with a parent, for the swap's put-back step, which moves nodes. */
interface TreeNode {
    nodeType: number
    id: string
    preserve: boolean
    parent: TreeNode | null
    children: TreeNode[]
    outerHTML: string
    hasAttribute(name: string): boolean
    querySelectorAll(selector: string): TreeNode[]
    contains(node: TreeNode): boolean
    replaceWith(node: TreeNode): void
}

function treeNode(id: string, { preserve = false, children = [] as TreeNode[] } = {}): TreeNode {
    const node: TreeNode = {
        nodeType: ELEMENT,
        id,
        preserve,
        parent: null,
        children,
        outerHTML: 'markup of ' + id,
        hasAttribute: (name: string) => name === 'hx-preserve' && node.preserve,
        querySelectorAll(selector: string) {
            expect(selector).toBe('[hx-preserve][id]')
            const found: TreeNode[] = []
            const walk = (n: TreeNode) => n.children.forEach((child) => {
                if (child.preserve && child.id) found.push(child)
                walk(child)
            })
            walk(node)
            return found
        },
        contains(other: TreeNode) {
            for (let n: TreeNode | null = other; n; n = n.parent) if (n === node) return true
            return false
        },
        replaceWith(other: TreeNode) {
            const parent = node.parent!
            if (other.parent) other.parent.children = other.parent.children.filter((child) => child !== other)
            parent.children = parent.children.map((child) => (child === node ? other : child))
            other.parent = parent
            node.parent = null
        },
    }
    children.forEach((child) => { child.parent = node })
    return node
}

/** What a morph builds from markup: an equal node that is not the same one. */
function copyOf(node: TreeNode): TreeNode {
    return treeNode(node.id, { preserve: node.preserve, children: node.children.map(copyOf) })
}

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

    test('puts the reader\'s own preserved element back over the copy the morph rebuilt', () => {
        // Without moveBefore, htmx parks the reader's preserved element in the
        // response itself, so the morph rebuilds it from markup. The node that
        // ends up on the page has to be the reader's: it holds the listeners,
        // the Alpine state and any refresh it has in flight.
        const readers = treeNode('findings-run1', { preserve: true, children: [treeNode('loaded-table')] })
        const incoming = treeNode('artifact-content', { children: [treeNode('summary'), readers, treeNode('danger')] })
        const target = treeNode('artifact-content', { children: [treeNode('summary'), treeNode('danger')] })
        const rebuild = mock((into: unknown, html: unknown) => {
            expect(html).toBe(incoming.outerHTML)
            const live = into as TreeNode
            live.children = incoming.children.map(copyOf)
            live.children.forEach((child) => { child.parent = live })
        })
        type Alpine = Parameters<typeof morphPreservingMarkedSubtrees>[0]

        morphPreservingMarkedSubtrees({ morph: rebuild } as unknown as Alpine, asElement(target), asNode(incoming))

        expect(target.children.map((child) => child.id)).toEqual(['summary', 'findings-run1', 'danger'])
        expect(target.children[1]).toBe(readers)
        expect(readers.parent).toBe(target)
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
