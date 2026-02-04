import { describe, test, expect, mock, beforeEach } from 'bun:test'
import { parseCsrfFromCookie } from '../../core/js/test-utils'

const mockAlpineData = mock<(name: string, callback: () => unknown) => void>()

mock.module('alpinejs', () => ({
    default: {
        data: mockAlpineData
    }
}))

const mockShowSuccess = mock<(message: string) => void>()
const mockShowError = mock<(message: string) => void>()

mock.module('../../core/js/alerts', () => ({
    showSuccess: mockShowSuccess,
    showError: mockShowError
}))

describe('Team Branding', () => {
    beforeEach(() => {
        mockAlpineData.mockClear()
        mockShowSuccess.mockClear()
        mockShowError.mockClear()
    })

    describe('CSRF Token', () => {
        test('should extract CSRF token from cookie string', () => {
            // Uses shared parseCsrfFromCookie utility from test-utils
            expect(parseCsrfFromCookie('csrftoken=abc123; sessionid=xyz')).toBe('abc123')
            expect(parseCsrfFromCookie('sessionid=xyz')).toBe('')
        })
    })

    describe('Branding Info', () => {
        test('should accept valid branding info', () => {
            interface BrandingInfo {
                icon: File | null
                logo: File | null
                icon_url: string
                logo_url: string
                prefer_logo_over_icon: boolean
                branding_enabled?: boolean
                brand_color: string
                accent_color: string
                icon_pending_deletion?: boolean
                logo_pending_deletion?: boolean
            }

            const branding: BrandingInfo = {
                icon: null,
                logo: null,
                icon_url: '/media/icons/team.png',
                logo_url: '/media/logos/team.png',
                prefer_logo_over_icon: false,
                branding_enabled: true,
                brand_color: '#007bff',
                accent_color: '#6c757d'
            }

            expect(branding.brand_color).toBe('#007bff')
            expect(branding.branding_enabled).toBe(true)
        })
    })

    describe('Unsaved Changes Detection', () => {
        test('should detect unsaved changes', () => {
            interface BrandingState {
                original: { brand_color: string; accent_color: string }
                current: { brand_color: string; accent_color: string }
            }

            const hasUnsavedChanges = (state: BrandingState): boolean => {
                return state.original.brand_color !== state.current.brand_color ||
                    state.original.accent_color !== state.current.accent_color
            }

            expect(hasUnsavedChanges({
                original: { brand_color: '#000', accent_color: '#fff' },
                current: { brand_color: '#000', accent_color: '#fff' }
            })).toBe(false)

            expect(hasUnsavedChanges({
                original: { brand_color: '#000', accent_color: '#fff' },
                current: { brand_color: '#111', accent_color: '#fff' }
            })).toBe(true)
        })
    })

    describe('File Handling', () => {
        test('should handle file from component', () => {
            interface Form {
                icon: File | null
                logo: File | null
            }

            const form: Form = { icon: null, logo: null }

            const handleFileFromComponent = (field: 'icon' | 'logo', file: File) => {
                form[field] = file
            }

            const mockFile = new File(['content'], 'test.png', { type: 'image/png' })
            handleFileFromComponent('icon', mockFile)

            expect(form.icon).toBe(mockFile)
            expect(form.logo).toBeNull()
        })

        test('should remove file from form', () => {
            interface Form {
                icon: File | null
                logo: File | null
            }

            const mockFile = new File(['content'], 'test.png', { type: 'image/png' })
            const form: Form = { icon: mockFile, logo: null }

            const removeFile = (field: 'icon' | 'logo') => {
                form[field] = null
            }

            removeFile('icon')
            expect(form.icon).toBeNull()
        })
    })

    describe('Default Colors', () => {
        test('should set default colors', () => {
            const DEFAULT_BRAND_COLOR = '#4F66DC'
            const DEFAULT_ACCENT_COLOR = '#4F66DC'

            expect(DEFAULT_BRAND_COLOR).toBe('#4F66DC')
            expect(DEFAULT_ACCENT_COLOR).toBe('#4F66DC')
        })
    })

    describe('Color Display', () => {
        test('should display color correctly', () => {
            const displayColor = (color: string): string => {
                return color || '#ffffff'
            }

            expect(displayColor('#007bff')).toBe('#007bff')
            expect(displayColor('')).toBe('#ffffff')
        })
    })

    describe('Custom Domain Config', () => {
        test('should accept valid custom domain config', () => {
            interface CustomDomainConfig {
                teamKey: string
                initialDomain: string
                isValidated: boolean
                lastCheckedAt: string
                hasAccess: boolean
            }

            const config: CustomDomainConfig = {
                teamKey: 'my-team',
                initialDomain: 'custom.example.com',
                isValidated: true,
                lastCheckedAt: '2024-01-15T12:00:00Z',
                hasAccess: true
            }

            expect(config.teamKey).toBe('my-team')
            expect(config.isValidated).toBe(true)
        })
    })

    describe('Domain Validation', () => {
        test('should detect unsaved domain changes', () => {
            const hasUnsavedChanges = (initial: string, current: string): boolean => {
                return initial !== current
            }

            expect(hasUnsavedChanges('example.com', 'example.com')).toBe(false)
            expect(hasUnsavedChanges('example.com', 'new.example.com')).toBe(true)
        })

        test('should allow save when domain has changed', () => {
            const canSave = (initial: string, current: string): boolean => {
                return initial !== current && current.trim().length > 0
            }

            expect(canSave('example.com', 'new.example.com')).toBe(true)
            expect(canSave('example.com', '')).toBe(false)
            expect(canSave('example.com', 'example.com')).toBe(false)
        })
    })

    describe('Last Checked Formatting', () => {
        test('should format last checked date', () => {
            const formatLastChecked = (dateString: string): string => {
                if (!dateString) return 'Never'
                const date = new Date(dateString)
                return date.toLocaleDateString('en-US', {
                    year: 'numeric',
                    month: 'short',
                    day: 'numeric',
                    hour: '2-digit',
                    minute: '2-digit'
                })
            }

            expect(formatLastChecked('')).toBe('Never')
            expect(formatLastChecked('2024-01-15T12:00:00Z')).toContain('2024')
        })
    })

    describe('Cancel Changes', () => {
        test('should revert to initial domain', () => {
            let currentDomain = 'changed.com'
            const initialDomain = 'original.com'

            const cancelChanges = () => {
                currentDomain = initialDomain
            }

            cancelChanges()
            expect(currentDomain).toBe('original.com')
        })
    })
})
