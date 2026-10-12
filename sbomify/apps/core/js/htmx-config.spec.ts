import { describe, test, expect, mock, afterEach } from 'bun:test'
import { registerHtmxConfig } from './htmx-config'
import { EXTENSION_NAME } from './htmx-morph-preserve'

// No DOM library in this repo, so the globals are the smallest shape
// registerHtmxConfig actually touches: htmx's extension and config registry,
// and one listener on the body.
interface Stubs {
    defined: string[]
    listeners: string[]
}

const saved = {
    window: (globalThis as Record<string, unknown>).window,
    document: (globalThis as Record<string, unknown>).document,
}

function installGlobals({ withHtmx = true } = {}): Stubs {
    const stubs: Stubs = { defined: [], listeners: [] }
    const htmx = {
        config: { attributesToSettle: ['class', 'style', 'width', 'height'] },
        defineExtension: mock((name: string) => {
            stubs.defined.push(name)
        }),
    }
    const g = globalThis as Record<string, unknown>
    g.window = withHtmx ? { htmx } : {}
    g.document = {
        body: {
            addEventListener: mock((name: string) => {
                stubs.listeners.push(name)
            }),
        },
    }
    return stubs
}

afterEach(() => {
    const g = globalThis as Record<string, unknown>
    g.window = saved.window
    g.document = saved.document
})

describe('registerHtmxConfig', () => {
    // The morph swap used to be registered by one bundle, so the page that
    // opts into it with hx-ext loaded a bundle that never defined it. htmx
    // does not report an unknown extension: it falls back to defaultSwapStyle,
    // which turns hx-swap="morph" into an innerHTML swap of the region into
    // itself. Every entry point calls this function, so the registration lives
    // here and no entry point can leave it out.
    test('registers the morph-preserve swap', () => {
        const stubs = installGlobals()

        registerHtmxConfig()

        expect(stubs.defined).toContain(EXTENSION_NAME)
    })

    test('keeps style out of the settle phase, so Alpine owns inline styles', () => {
        installGlobals()

        registerHtmxConfig()

        const { htmx } = (globalThis as unknown as {
            window: { htmx: { config: { attributesToSettle: string[] } } }
        }).window
        expect(htmx.config.attributesToSettle).not.toContain('style')
        expect(htmx.config.attributesToSettle).toContain('class')
    })

    test('still attaches the CSRF handler when htmx has not loaded', () => {
        const stubs = installGlobals({ withHtmx: false })

        registerHtmxConfig()

        expect(stubs.defined).toEqual([])
        expect(stubs.listeners).toContain('htmx:configRequest')
    })
})
