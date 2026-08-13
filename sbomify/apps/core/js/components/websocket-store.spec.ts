import { describe, test, expect, mock, beforeEach, afterEach } from 'bun:test'

interface StoredSocket {
    url: string
    closed: { code: number; reason: string } | null
    onopen: (() => void) | null
    onmessage: ((event: { data: string }) => void) | null
    onclose: ((event: { code: number; reason: string; wasClean: boolean }) => void) | null
    onerror: (() => void) | null
}

const sockets: FakeWebSocket[] = []

class FakeWebSocket implements StoredSocket {
    static OPEN = 1
    url: string
    closed: { code: number; reason: string } | null = null
    onopen: (() => void) | null = null
    onmessage: ((event: { data: string }) => void) | null = null
    onclose: ((event: { code: number; reason: string; wasClean: boolean }) => void) | null = null
    onerror: (() => void) | null = null

    constructor(url: string) {
        this.url = url
        sockets.push(this)
    }

    close(code: number, reason: string): void {
        this.closed = { code, reason }
    }

    /** Drive a successful handshake. */
    open(): void {
        this.onopen?.()
    }

    /** Drive a close the way a browser would after a drop or a rejected handshake. */
    drop(wasClean = false, code = 1006): void {
        this.onclose?.({ code, reason: '', wasClean })
    }
}

const stores: Record<string, unknown> = {}

mock.module('alpinejs', () => ({
    default: {
        store: (name: string, value?: unknown) => {
            if (value !== undefined) {
                stores[name] = value
                return undefined
            }
            return stores[name]
        }
    }
}))

interface WsStore {
    connect: (workspaceKey: string) => void
    disconnect: () => void
    connected: boolean
    reconnectAttempts: number
    socket: FakeWebSocket | null
}

const { registerWebSocketStore } = await import('./websocket-store')

/** Timers the store scheduled, so tests can run them without waiting. */
const pending: { id: number; fn: () => void; delay: number }[] = []
let nextTimerId = 1

/** The stability credit the store arms on open; see CONNECTION_STABLE_AFTER_MS. */
const STABLE_DELAY_MS = 5000

/** Mirrors RECONNECT_MAX_ATTEMPTS in the store, which is not exported. */
const RECONNECT_MAX_ATTEMPTS = 10

/** Run the stability credit, if one is armed, so the budget is refunded. */
function runStableTimer(): void {
    const at = pending.findIndex((timer) => timer.delay === STABLE_DELAY_MS)
    if (at === -1) throw new Error('expected a stability credit to be armed, none was')
    const [timer] = pending.splice(at, 1)
    timer.fn()
}

const globals = globalThis as unknown as Record<string, unknown>
const realGlobals: Record<string, unknown> = {
    WebSocket: globals.WebSocket,
    window: globals.window,
    CustomEvent: globals.CustomEvent,
    setTimeout: globals.setTimeout,
    clearTimeout: globals.clearTimeout
}
const realRandom = Math.random

function restoreGlobals(): void {
    for (const [name, value] of Object.entries(realGlobals)) {
        if (value === undefined) {
            delete globals[name]
        } else {
            globals[name] = value
        }
    }
    Math.random = realRandom
}

function getStore(): WsStore {
    return stores.ws as WsStore
}

/** Run the reconnect timer the store is waiting on, returning its delay. */
function runPendingTimer(): number {
    const at = pending.findIndex((timer) => timer.delay !== STABLE_DELAY_MS)
    if (at === -1) throw new Error('expected a reconnect to be scheduled, none was')
    const [timer] = pending.splice(at, 1)
    timer.fn()
    return timer.delay
}

describe('WebSocket store reconnection', () => {
    beforeEach(() => {
        sockets.length = 0
        pending.length = 0

        ;(globalThis as unknown as { WebSocket: unknown }).WebSocket = FakeWebSocket
        ;(globalThis as unknown as { window: unknown }).window = {
            location: { protocol: 'https:', host: 'app.sbomify.com' },
            dispatchEvent: () => true
        }
        ;(globalThis as unknown as { CustomEvent: unknown }).CustomEvent = class {
            constructor(
                public type: string,
                public init?: { detail?: unknown }
            ) {}
        }
        // Jitter is proportional, so pinning it keeps the backoff assertions exact.
        Math.random = () => 0
        // Handle-aware, because the store now runs two timers at once (the
        // reconnect backoff and the stability credit) and a clearTimeout that
        // wiped both would hide the very bug these tests exist to catch.
        nextTimerId = 1
        ;(globalThis as unknown as { setTimeout: unknown }).setTimeout = (fn: () => void, delay: number) => {
            const id = nextTimerId++
            pending.push({ id, fn, delay })
            return id
        }
        ;(globalThis as unknown as { clearTimeout: unknown }).clearTimeout = (id: number) => {
            const at = pending.findIndex((timer) => timer.id === id)
            if (at !== -1) pending.splice(at, 1)
        }

        registerWebSocketStore()
    })

    afterEach(() => {
        restoreGlobals()
    })

    test('retries when the very first handshake is refused', () => {
        // A backend restart while the page loads means onopen never fires. The
        // tab has no live updates at all, so this is the case that most needs a
        // retry, and it was the one case that got none.
        getStore().connect('workspace-key')
        sockets[0].drop()

        expect(runPendingTimer()).toBe(1000)
        expect(sockets).toHaveLength(2)
    })

    test('retries when the server closes cleanly, as a graceful deploy does', () => {
        // docker stop / a deploy shuts uvicorn down gracefully, so the browser
        // sees a completed close handshake (wasClean=true). Gating the retry on
        // wasClean left every open tab dead after each deploy — and deliberate
        // client disconnects detach the handler entirely, so any close that
        // reaches it is the server's doing.
        getStore().connect('workspace-key')
        sockets[0].open()
        sockets[0].drop(true, 1001)

        expect(runPendingTimer()).toBe(1000)
        expect(sockets).toHaveLength(2)
    })

    test('backs off across consecutive failures instead of retrying every second', () => {
        getStore().connect('workspace-key')
        sockets[0].open()

        const delays: number[] = []
        for (let i = 0; i < 4; i++) {
            sockets[sockets.length - 1].drop()
            delays.push(runPendingTimer())
        }

        expect(delays).toEqual([1000, 2000, 4000, 8000])
    })

    test('gives up once the attempt budget is spent', () => {
        getStore().connect('workspace-key')
        sockets[0].open()

        for (let i = 0; i < 10; i++) {
            sockets[sockets.length - 1].drop()
            runPendingTimer()
        }
        sockets[sockets.length - 1].drop()

        expect(pending).toHaveLength(0)
    })

    test('a reconnect that succeeds restores the full attempt budget', () => {
        getStore().connect('workspace-key')
        sockets[0].open()
        runStableTimer()

        sockets[0].drop()
        runPendingTimer()
        sockets[1].open()
        runStableTimer()
        sockets[1].drop()

        expect(runPendingTimer()).toBe(1000)
    })

    test('a socket that closes immediately does not restore the budget', () => {
        // The server accepts the handshake before applying its verdict, so a
        // rejected connection still fires onopen. Refunding the budget there
        // meant a broker outage never backed off: every rejection restarted the
        // delay at one second and the attempt cap was never reached.
        getStore().connect('workspace-key')

        sockets[0].open()
        sockets[0].drop() // closed well inside the stability window
        expect(runPendingTimer()).toBe(1000)

        sockets[1].open()
        sockets[1].drop()

        expect(runPendingTimer()).toBe(2000)
    })

    test('an accept-then-close loop still exhausts the attempt budget', () => {
        // The consequence that matters: without this, every open tab retries
        // once per second for the whole outage against an already-degraded
        // server, and never gives up.
        getStore().connect('workspace-key')

        for (let attempt = 0; attempt < RECONNECT_MAX_ATTEMPTS; attempt++) {
            sockets[sockets.length - 1].open()
            sockets[sockets.length - 1].drop()
            runPendingTimer()
        }

        sockets[sockets.length - 1].open()
        sockets[sockets.length - 1].drop()

        expect(pending.filter((timer) => timer.delay !== STABLE_DELAY_MS)).toHaveLength(0)
    })

    test('the stability credit is dropped when the socket closes', () => {
        // Left armed, it would refund the budget after the fact and undo the
        // backoff a moment later.
        getStore().connect('workspace-key')
        sockets[0].open()
        sockets[0].drop()

        expect(pending.filter((timer) => timer.delay === STABLE_DELAY_MS)).toHaveLength(0)
    })

    test('does not retry close codes that can never succeed', () => {
        // 1008 policy violation, 1002 protocol error, 1003 unsupported data:
        // terminal verdicts about the client, so retrying is a slow no-op loop.
        for (const code of [1008, 1002, 1003]) {
            getStore().connect('workspace-key')
            sockets[sockets.length - 1].open()
            sockets[sockets.length - 1].drop(true, code)

            expect(pending).toHaveLength(0)
            getStore().disconnect()
        }
    })

    test('does not reconnect after a deliberate disconnect', () => {
        const store = getStore()
        store.connect('workspace-key')
        sockets[0].open()

        store.disconnect()
        sockets[0].drop(true, 1000)

        expect(pending).toHaveLength(0)
        expect(sockets).toHaveLength(1)
    })

    test('a replaced socket closing late does not tear down the live one', () => {
        const store = getStore()
        store.connect('workspace-a')
        sockets[0].open()

        // connect() closes the old socket, but the browser fires its close event
        // asynchronously — by then the new socket is the one in the store.
        store.connect('workspace-b')
        sockets[1].open()
        sockets[0].drop(true, 1000)

        expect(store.connected).toBe(true)
        expect(store.socket).toBe(sockets[1])
    })

    test('connects to the workspace-scoped wss URL', () => {
        getStore().connect('workspace-key')

        expect(sockets[0].url).toBe('wss://app.sbomify.com/ws/workspace/workspace-key/')
    })
})
