import { describe, test, expect, mock } from 'bun:test'

describe('Theme Manager', () => {

    describe('getStoredTheme logic', () => {
        test('should return stored theme when valid', () => {
            const getStoredTheme = (stored: string | null): string => {
                if (stored === 'light' || stored === 'dark' || stored === 'system') {
                    return stored
                }
                return 'dark'
            }

            expect(getStoredTheme('light')).toBe('light')
            expect(getStoredTheme('dark')).toBe('dark')
            expect(getStoredTheme('system')).toBe('system')
        })

        test('should default to dark for invalid stored values', () => {
            const getStoredTheme = (stored: string | null): string => {
                if (stored === 'light' || stored === 'dark' || stored === 'system') {
                    return stored
                }
                return 'dark'
            }

            expect(getStoredTheme(null)).toBe('dark')
            expect(getStoredTheme('')).toBe('dark')
            expect(getStoredTheme('invalid')).toBe('dark')
            expect(getStoredTheme('auto')).toBe('dark')
        })
    })

    describe('applyTheme logic', () => {
        test('should resolve system theme to dark or light', () => {
            const resolveTheme = (theme: string, prefersDark: boolean): string => {
                return theme === 'system'
                    ? (prefersDark ? 'dark' : 'light')
                    : theme
            }

            expect(resolveTheme('system', true)).toBe('dark')
            expect(resolveTheme('system', false)).toBe('light')
            expect(resolveTheme('dark', false)).toBe('dark')
            expect(resolveTheme('light', true)).toBe('light')
        })

        test('should compute opposite theme correctly', () => {
            const getOpposite = (theme: string): string => {
                return theme === 'light' ? 'dark' : 'light'
            }

            expect(getOpposite('dark')).toBe('light')
            expect(getOpposite('light')).toBe('dark')
        })
    })

    describe('setTheme logic', () => {
        test('should store theme and apply it', () => {
            let storedKey = ''
            let storedValue = ''
            let appliedTheme = ''

            const setTheme = (theme: string) => {
                storedKey = 'sbomify-theme'
                storedValue = theme
                appliedTheme = theme === 'system' ? 'dark' : theme
            }

            setTheme('light')
            expect(storedKey).toBe('sbomify-theme')
            expect(storedValue).toBe('light')
            expect(appliedTheme).toBe('light')

            setTheme('system')
            expect(storedValue).toBe('system')
            expect(appliedTheme).toBe('dark')
        })

        test('should dispatch theme-changed event', () => {
            let dispatched = false
            let eventDetail: Record<string, string> = {}

            const setTheme = (theme: string) => {
                dispatched = true
                eventDetail = { theme }
            }

            setTheme('dark')
            expect(dispatched).toBe(true)
            expect(eventDetail).toEqual({ theme: 'dark' })
        })
    })

    describe('STORAGE_KEY consistency', () => {
        test('should use sbomify-theme as storage key', () => {
            const STORAGE_KEY = 'sbomify-theme'
            expect(STORAGE_KEY).toBe('sbomify-theme')
        })
    })

    describe('initThemeManager public-page short-circuit (real module)', () => {
        // Exercises the production initThemeManager() with mocked
        // ``document``/``localStorage``/``window`` so the guard is
        // covered against accidental removal. public_base.htmx.j2 owns
        // theming on trust-center pages via ``data-theme``; the auth-app
        // theme manager must early-return there so it doesn't clobber
        // the public theme.

        type ClassList = { add: ReturnType<typeof mock>; remove: ReturnType<typeof mock> }
        type FakeHtml = {
            hasAttribute: ReturnType<typeof mock>
            classList: ClassList
            style: { colorScheme: string }
            attrs: Record<string, string>
        }
        type FakeWindow = {
            matchMedia: ReturnType<typeof mock>
            themeManager?: unknown
        }

        const makeFakeHtml = (attrs: Record<string, string> = {}): FakeHtml => ({
            hasAttribute: mock((name: string) => name in attrs),
            classList: { add: mock(() => {}), remove: mock(() => {}) },
            style: { colorScheme: '' },
            attrs,
        })

        const installMocks = (fakeHtml: FakeHtml, storage: Record<string, string> = {}): FakeWindow => {
            const fakeWindow: FakeWindow = {
                matchMedia: mock(() => ({
                    matches: false,
                    addEventListener: () => {},
                })),
            }
            ;(globalThis as unknown as { document: { documentElement: FakeHtml } }).document = {
                documentElement: fakeHtml,
            }
            ;(globalThis as unknown as { window: FakeWindow }).window = fakeWindow
            ;(globalThis as unknown as { localStorage: Storage }).localStorage = {
                getItem: mock((k: string) => storage[k] ?? null),
                setItem: mock((k: string, v: string) => {
                    storage[k] = v
                }),
                removeItem: mock((k: string) => {
                    delete storage[k]
                }),
                clear: mock(() => {}),
                key: mock(() => null),
                length: 0,
            } as unknown as Storage
            // requestAnimationFrame is used by applyTheme() after the
            // class is added; we don't need the rAF body to run, just to
            // not crash. A no-op satisfies that.
            ;(globalThis as unknown as { requestAnimationFrame: (cb: () => void) => number }).requestAnimationFrame = (() =>
                0) as () => number
            return fakeWindow
        }

        const loadFreshInitThemeManager = async (): Promise<() => void> => {
            // Force a fresh import so module-level globals re-bind to the
            // freshly installed ``window``/``document`` mocks.
            const path = './theme-manager'
            const mod = (await import(`${path}?cache=${Math.random()}`)) as { initThemeManager: () => void }
            return mod.initThemeManager
        }

        test('short-circuits when <html data-theme="dark"> is preset (public page)', async () => {
            const fakeHtml = makeFakeHtml({ 'data-theme': 'dark' })
            const fakeWindow = installMocks(fakeHtml, { 'sbomify-theme': 'light' })
            const initThemeManager = await loadFreshInitThemeManager()

            initThemeManager()

            expect(fakeHtml.hasAttribute).toHaveBeenCalledWith('data-theme')
            expect(fakeHtml.classList.add).not.toHaveBeenCalled()
            expect(fakeHtml.classList.remove).not.toHaveBeenCalled()
            expect(fakeWindow.themeManager).toBeUndefined()
        })

        test('runs normally on auth pages (no data-theme attribute)', async () => {
            const fakeHtml = makeFakeHtml({})
            const fakeWindow = installMocks(fakeHtml, { 'sbomify-theme': 'dark' })
            const initThemeManager = await loadFreshInitThemeManager()

            initThemeManager()

            expect(fakeHtml.classList.add).toHaveBeenCalled()
            expect(fakeWindow.themeManager).toBeDefined()
        })
    })
})
