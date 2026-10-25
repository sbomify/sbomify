import { describe, test, expect, beforeEach, afterEach } from 'bun:test'
import { liveRegion } from './live-region'

type Timer = { fn: () => void; delay: number }

const globals = globalThis as unknown as Record<string, unknown>
const saved = {
    setTimeout: globals.setTimeout,
    clearTimeout: globals.clearTimeout,
    window: globals.window,
    document: globals.document,
    CustomEvent: globals.CustomEvent,
}

let timers: Timer[]
let fired: number
let left: string[]
let focusInside: boolean
let focusedIsField: boolean
let focusout: (() => void) | null
let wsListener: ((event: Event) => void) | null

function region(overrides: Partial<Parameters<typeof liveRegion>[0]> = {}) {
    const scope = Object.assign(
        liveRegion({
            refresh: ['release_updated'],
            remove: ['release_deleted'],
            key: 'release_id',
            id: 'rel-1',
            leaveTo: '/product/p-1/releases/',
            ...overrides,
        }),
        {
            $el: {
                contains: () => focusInside,
                addEventListener: (_: string, fn: () => void) => {
                    focusout = fn
                },
                dispatchEvent: (event: { type: string }) => {
                    if (event.type === 'live-refresh') fired += 1
                    return true
                },
            } as unknown as HTMLElement,
        },
    )
    scope.init()
    return scope
}

function send(detail: Record<string, unknown>): void {
    wsListener?.({ detail } as unknown as Event)
}

function runTimers(): void {
    while (timers.length) timers.shift()!.fn()
}

describe('a live region', () => {
    beforeEach(() => {
        timers = []
        fired = 0
        left = []
        focusInside = false
        focusedIsField = true
        focusout = null
        wsListener = null
        globals.setTimeout = (fn: () => void, delay: number) => {
            timers.push({ fn, delay })
            return timers.length
        }
        globals.clearTimeout = () => {
            timers.length = 0
        }
        globals.window = {
            addEventListener: (_: string, fn: (event: Event) => void) => {
                wsListener = fn
            },
            location: { assign: (url: string) => left.push(url) },
        }
        globals.document = {
            get activeElement() {
                return focusInside ? { matches: () => focusedIsField } : null
            },
        }
        globals.CustomEvent = class {
            constructor(public type: string) {}
        }
    })

    afterEach(() => {
        for (const [name, value] of Object.entries(saved)) globals[name] = value
    })

    test('refreshes once after a burst of updates about its subject', () => {
        region()
        send({ type: 'release_updated', release_id: 'rel-1' })
        send({ type: 'release_updated', release_id: 'rel-1' })
        runTimers()

        expect(fired).toBe(1)
    })

    test('ignores updates about something else', () => {
        region()
        send({ type: 'release_updated', release_id: 'rel-2' })
        send({ type: 'component_updated', release_id: 'rel-1' })
        runTimers()

        expect(fired).toBe(0)
    })

    test('a resync refreshes whatever it is about', () => {
        region()
        send({ type: 'resync' })
        runTimers()

        expect(fired).toBe(1)
    })

    test('leaves the page when its subject is deleted', () => {
        region()
        send({ type: 'release_deleted', release_id: 'rel-1' })

        expect(left).toEqual(['/product/p-1/releases/'])
        expect(fired).toBe(0)
    })

    test('a deletion of something else stays put', () => {
        region()
        send({ type: 'release_deleted', release_id: 'rel-2' })

        expect(left).toEqual([])
    })

    test('waits while the reader is editing inside it, then refreshes when they leave', () => {
        region()
        focusInside = true
        send({ type: 'release_updated', release_id: 'rel-1' })
        runTimers()
        expect(fired).toBe(0)

        focusInside = false
        focusout?.()
        runTimers()

        expect(fired).toBe(1)
    })

    test('leaving the region with nothing due does not refresh', () => {
        region()
        focusout?.()
        runTimers()

        expect(fired).toBe(0)
    })

    test('a focused button does not hold a refresh back', () => {
        region()
        focusInside = true
        focusedIsField = false
        send({ type: 'release_updated', release_id: 'rel-1' })
        runTimers()

        expect(fired).toBe(1)
    })
})
