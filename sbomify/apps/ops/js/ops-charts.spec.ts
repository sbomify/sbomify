import { describe, test, expect, beforeAll, afterEach } from 'bun:test'

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

    beforeAll(async () => {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const g = globalThis as any
        g.window = globalThis
        g.document = { querySelectorAll: () => [] }
        g.getComputedStyle = () => ({ getPropertyValue: () => tokenValue })
        g.Chart = class {
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            constructor(_canvas: any, config: any) {
                built.push(config)
            }
            destroy() {
                destroyCalls.count++
            }
        }
        initOpsCharts = (await import('./ops-charts')).initOpsCharts
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
