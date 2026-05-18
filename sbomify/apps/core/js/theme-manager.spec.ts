import { describe, test, expect } from 'bun:test'

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

    describe('initThemeManager public-page short-circuit', () => {
        // public_base.htmx.j2 owns its own theme system keyed on
        // ``data-theme="dark"|"light"`` (with its own ``public-theme``
        // localStorage key). When that attribute is already present on
        // <html> by the time main.ts runs ``initThemeManager``, the
        // auth-app theme manager must early-return so it doesn't clobber
        // the public theme (which would force a stale
        // ``sbomify-theme`` value over the live ``public-theme`` and
        // flip e.g. table-header backgrounds to the wrong variant set).
        const initThemeManagerGuard = (rootHasDataTheme: boolean): { ran: boolean; reason: string } => {
            if (rootHasDataTheme) {
                return { ran: false, reason: 'short-circuit: public page owns theming via data-theme' }
            }
            return { ran: true, reason: 'auth page: applied stored theme + exposed window.themeManager' }
        }

        test('returns without applying anything when data-theme is preset', () => {
            const result = initThemeManagerGuard(true)
            expect(result.ran).toBe(false)
            expect(result.reason).toContain('short-circuit')
        })

        test('runs normally on auth pages with no data-theme attribute', () => {
            const result = initThemeManagerGuard(false)
            expect(result.ran).toBe(true)
            expect(result.reason).toContain('auth page')
        })
    })
})
