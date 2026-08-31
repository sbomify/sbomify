import { describe, test, expect, beforeEach, afterEach } from 'bun:test'
import { actionsMenu, menuPosition } from './actions-menu'

const VIEWPORT = { width: 1000, height: 800 }

describe('positioning the menu', () => {
    test('hangs below the trigger, right edges aligned', () => {
        const style = menuPosition({ top: 100, bottom: 140, right: 900 }, 200, VIEWPORT)

        expect(style).toBe('right: 100px; top: 148px;')
    })

    test('flips above when there is no room below', () => {
        const style = menuPosition({ top: 700, bottom: 740, right: 900 }, 200, VIEWPORT)

        // Anchored by its bottom edge to the trigger's top, so its height does
        // not have to fit under the trigger.
        expect(style).toBe('right: 100px; bottom: 108px;')
    })

    test('stays below when the space below is tight but still the roomier side', () => {
        const style = menuPosition({ top: 300, bottom: 340, right: 900 }, 600, VIEWPORT)

        expect(style).toBe('right: 100px; top: 348px;')
    })

    test('a short menu near the bottom still hangs below', () => {
        const style = menuPosition({ top: 700, bottom: 740, right: 900 }, 40, VIEWPORT)

        expect(style).toBe('right: 100px; top: 748px;')
    })

    test('keeps a margin when the trigger is hard against the right edge', () => {
        const style = menuPosition({ top: 100, bottom: 140, right: 1000 }, 200, VIEWPORT)

        expect(style).toBe('right: 8px; top: 148px;')
    })
})

describe('opening and closing', () => {
    let menu: ReturnType<typeof actionsMenu> & { $refs: Record<string, HTMLElement | undefined> }
    let focused: number

    beforeEach(() => {
        focused = 0
        menu = Object.assign(actionsMenu(), {
            $refs: {
                trigger: {
                    getBoundingClientRect: () => ({ top: 100, bottom: 140, right: 900 }),
                    focus: () => {
                        focused += 1
                    },
                } as unknown as HTMLElement,
                menu: { offsetHeight: 200 } as unknown as HTMLElement,
            },
        })
        globalThis.window = {
            innerWidth: VIEWPORT.width,
            innerHeight: VIEWPORT.height,
            addEventListener: () => {},
            removeEventListener: () => {},
        } as unknown as Window & typeof globalThis
    })

    afterEach(async () => {
        // Let any positioning a test scheduled run before the stub goes away,
        // or it lands in the next test with no window to measure against.
        await new Promise((resolve) => setTimeout(resolve))
        delete (globalThis as { window?: unknown }).window
    })

    test('starts closed and unpositioned', () => {
        expect(menu.open).toBe(false)
        expect(menu.style).toBe('')
    })

    test('opening positions the menu against the trigger', async () => {
        menu.toggle()
        await new Promise((resolve) => setTimeout(resolve))

        expect(menu.open).toBe(true)
        expect(menu.style).toBe('right: 100px; top: 148px;')
    })

    test('toggling again closes it', () => {
        menu.toggle()
        menu.toggle()

        expect(menu.open).toBe(false)
    })

    test('the menu is hidden until it has been measured', () => {
        // Synchronously after opening — what the browser would paint on the
        // tick between opening and positioning.
        menu.show()

        expect(menu.style).toBe('visibility: hidden;')
    })

    test('positioning without a rendered menu leaves it hidden rather than misplaced', async () => {
        menu.$refs.menu = undefined
        menu.show()
        await new Promise((resolve) => setTimeout(resolve))

        expect(menu.style).toBe('visibility: hidden;')
    })

    test('escape closes the open menu and returns focus to its trigger', () => {
        menu.toggle()
        menu.closeAndFocus()

        expect(menu.open).toBe(false)
        expect(focused).toBe(1)
    })

    test('escape does not steal focus for a menu that is already closed', () => {
        menu.closeAndFocus()

        expect(focused).toBe(0)
    })

    test('a scroll or resize dismisses it, and the listeners come back off', () => {
        const events: string[] = []
        globalThis.window = {
            ...globalThis.window,
            addEventListener: (name: string) => events.push(`+${name}`),
            removeEventListener: (name: string) => events.push(`-${name}`),
        } as unknown as Window & typeof globalThis

        menu.init()
        menu.toggle()
        menu.dismiss?.()
        expect(menu.open).toBe(false)

        menu.destroy()
        expect(events).toEqual(['+scroll', '+resize', '-scroll', '-resize'])
    })
})
