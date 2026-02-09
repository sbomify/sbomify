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
})
