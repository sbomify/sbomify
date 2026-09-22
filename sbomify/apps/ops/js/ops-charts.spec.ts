import { describe, test, expect, beforeAll, afterAll, afterEach } from 'bun:test'

// Exercises the real initOpsCharts against fake DOM objects. The bun test env
// has no DOM, and the function only touches root.querySelectorAll, the canvas
// dataset, getComputedStyle and window.Chart, so faithful stubs reach the code
// that actually ships. The Django tests can only see the rendered HTML, which
// cannot catch a regression in dataset decoding or in the Chart config.
describe('Ops charts', () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    let initOpsCharts: (root?: any) => void
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const built: any[] = []
    const destroyCalls = { count: 0 }
    let tokenValue = 'rgb(124 140 255)'

    // bun runs every spec in one process, so a global set here is a global set
    // for the whole suite. Assigning `window = globalThis` in particular leaves
    // axios, imported by the table specs, reading `window.location.href` off an
    // object that has no location. Stub exactly what the module needs, record
    // what was there, and put it back.
    const originalGlobals: Record<string, { existed: boolean; value: unknown }> = {}

    const stub = (key: string, value: unknown) => {
        const g = globalThis as unknown as Record<string, unknown>
        originalGlobals[key] = { existed: key in g, value: g[key] }
        g[key] = value
    }

    beforeAll(async () => {
        class FakeChart {
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            constructor(_canvas: any, config: any) {
                built.push(config)
            }
            destroy() {
                destroyCalls.count++
            }
        }

        // The module reads window.Chart and calls getComputedStyle. location is
        // here so anything that peeks at window during this file still finds a
        // browser-shaped object.
        stub('window', { Chart: FakeChart, location: { href: 'http://localhost/' } })
        // accentColor reads the token off document.documentElement.
        stub('document', { documentElement: {}, querySelectorAll: () => [] })
        stub('getComputedStyle', () => ({ getPropertyValue: () => tokenValue }))

        initOpsCharts = (await import('./ops-charts')).initOpsCharts
    })

    afterAll(() => {
        const g = globalThis as unknown as Record<string, unknown>
        for (const [key, { existed, value }] of Object.entries(originalGlobals)) {
            if (existed) {
                g[key] = value
            } else {
                delete g[key]
            }
        }
    })

    afterEach(() => {
        built.length = 0
        destroyCalls.count = 0
        tokenValue = 'rgb(124 140 255)'
    })

     
    const canvasOf = (dataset: Record<string, string>) => ({ dataset, getContext: () => ({}) })
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const rootOf = (...canvases: any[]) => ({ querySelectorAll: () => canvases })

    test('decodes the signup series out of its data attributes', () => {
        const canvas = canvasOf({
            chart: 'signups',
            labels: JSON.stringify(['2026-09-01', '2026-09-02']),
            values: JSON.stringify([0, 4]),
        })

        initOpsCharts(rootOf(canvas))

        expect(built).toHaveLength(1)
        expect(built[0].type).toBe('line')
        expect(built[0].data.datasets[0].data).toEqual([0, 4])
        // Zero-filled days must survive decoding, or the trend lies.
        expect(built[0].data.labels).toHaveLength(2)
    })

    test('keeps a plan label with an apostrophe intact', () => {
        // The old dashboard pasted labels into a script body, where Django's
        // escaping turned an apostrophe into a visible &#x27;.
        const canvas = canvasOf({
            chart: 'plans',
            labels: JSON.stringify(["Bob's plan", 'community']),
            values: JSON.stringify([1, 2]),
        })

        initOpsCharts(rootOf(canvas))

        expect(built[0].data.labels[0]).toBe("Bob's plan")
        expect(built[0].type).toBe('bar')
    })

    test('survives a malformed data attribute instead of throwing', () => {
        const canvas = canvasOf({ chart: 'signups', labels: 'not json', values: 'not json' })

        expect(() => initOpsCharts(rootOf(canvas))).not.toThrow()
        expect(built[0].data.datasets[0].data).toEqual([])
    })

    test('ignores a canvas with an unknown chart kind', () => {
        const canvas = canvasOf({ chart: 'nonsense', labels: '[]', values: '[]' })

        initOpsCharts(rootOf(canvas))

        expect(built).toHaveLength(0)
    })

    test('converts a bare channel token into an rgb colour', () => {
        tokenValue = '37 41 63'
        const canvas = canvasOf({ chart: 'plans', labels: '["a"]', values: '[1]' })

        initOpsCharts(rootOf(canvas))

        expect(built[0].data.datasets[0].backgroundColor).toBe('rgb(37 41 63)')
    })

    test('falls back to the shared brand constant when the token is absent', () => {
        tokenValue = ''
        const canvas = canvasOf({ chart: 'plans', labels: '["a"]', values: '[1]' })

        initOpsCharts(rootOf(canvas))

        // The shared constant, not a hex private to the chart module.
        expect(built[0].data.datasets[0].backgroundColor).toBe('#4263EB')
    })

    test('destroys a prior chart before rebuilding the same canvas', () => {
        const canvas = canvasOf({ chart: 'plans', labels: '["a"]', values: '[1]' })
        const root = rootOf(canvas)

        initOpsCharts(root)
        initOpsCharts(root)

        expect(destroyCalls.count).toBe(1)
        expect(built).toHaveLength(2)
    })
})
