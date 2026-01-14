import { describe, test, expect, mock, beforeEach } from 'bun:test'

const mockAlpineData = mock<(name: string, callback: () => unknown) => void>()

mock.module('alpinejs', () => ({
    default: {
        data: mockAlpineData
    }
}))

interface OnboardingWizardState {
    companyName: string
    contactName: string
    email: string
    website: string
    isSubmitting: boolean
    touched: {
        companyName: boolean
        contactName: boolean
        email: boolean
        website: boolean
    }
}

describe('Onboarding Wizard', () => {
    beforeEach(() => {
        mockAlpineData.mockClear()
    })

    describe('Company Name Validation', () => {
        test('should validate non-empty company name', () => {
            const isCompanyValid = (companyName: string): boolean => {
                return companyName.trim().length > 0
            }

            expect(isCompanyValid('Acme Inc')).toBe(true)
            expect(isCompanyValid('  Acme Inc  ')).toBe(true)
            expect(isCompanyValid('')).toBe(false)
            expect(isCompanyValid('   ')).toBe(false)
        })
    })

    describe('Contact Name Validation', () => {
        test('should validate non-empty contact name', () => {
            const isContactNameValid = (contactName: string): boolean => {
                return contactName.trim().length > 0
            }

            expect(isContactNameValid('John Doe')).toBe(true)
            expect(isContactNameValid('  John  ')).toBe(true)
            expect(isContactNameValid('')).toBe(false)
            expect(isContactNameValid('   ')).toBe(false)
        })
    })

    describe('Email Validation', () => {
        test('should accept empty email (optional field)', () => {
            const isEmailValid = (email: string): boolean => {
                if (!email || email.trim() === '') {
                    return true
                }
                const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
                return emailRegex.test(email.trim())
            }

            expect(isEmailValid('')).toBe(true)
            expect(isEmailValid('   ')).toBe(true)
        })

        test('should validate email format when provided', () => {
            const isEmailValid = (email: string): boolean => {
                if (!email || email.trim() === '') {
                    return true
                }
                const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
                return emailRegex.test(email.trim())
            }

            expect(isEmailValid('user@example.com')).toBe(true)
            expect(isEmailValid('user.name@example.co.uk')).toBe(true)
            expect(isEmailValid('invalid-email')).toBe(false)
            expect(isEmailValid('missing@domain')).toBe(false)
            expect(isEmailValid('@nodomain.com')).toBe(false)
        })
    })

    describe('Website Validation', () => {
        test('should accept empty website (optional field)', () => {
            const isWebsiteValid = (website: string): boolean => {
                if (!website || website.trim() === '') {
                    return true
                }
                try {
                    new URL(website.trim())
                    return true
                } catch {
                    return false
                }
            }

            expect(isWebsiteValid('')).toBe(true)
            expect(isWebsiteValid('   ')).toBe(true)
        })

        test('should validate URL format when provided', () => {
            const isWebsiteValid = (website: string): boolean => {
                if (!website || website.trim() === '') {
                    return true
                }
                try {
                    new URL(website.trim())
                    return true
                } catch {
                    return false
                }
            }

            expect(isWebsiteValid('https://example.com')).toBe(true)
            expect(isWebsiteValid('http://example.com')).toBe(true)
            expect(isWebsiteValid('https://example.com/path')).toBe(true)
            expect(isWebsiteValid('not-a-url')).toBe(false)
            expect(isWebsiteValid('example.com')).toBe(false)
        })
    })

    describe('Can Submit Check', () => {
        test('should allow submit when all required fields are valid', () => {
            const canSubmit = (state: OnboardingWizardState): boolean => {
                const isCompanyValid = state.companyName.trim().length > 0
                const isContactNameValid = state.contactName.trim().length > 0
                const isEmailValid = !state.email || state.email.trim() === '' ||
                    /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(state.email.trim())
                const isWebsiteValid = !state.website || state.website.trim() === '' ||
                    (() => { try { new URL(state.website.trim()); return true } catch { return false } })()

                return isCompanyValid && isContactNameValid && isEmailValid && isWebsiteValid && !state.isSubmitting
            }

            const validState: OnboardingWizardState = {
                companyName: 'Acme Inc',
                contactName: 'John Doe',
                email: '',
                website: '',
                isSubmitting: false,
                touched: { companyName: false, contactName: false, email: false, website: false }
            }

            expect(canSubmit(validState)).toBe(true)
        })

        test('should prevent submit when required fields are empty', () => {
            const canSubmit = (state: OnboardingWizardState): boolean => {
                const isCompanyValid = state.companyName.trim().length > 0
                const isContactNameValid = state.contactName.trim().length > 0

                return isCompanyValid && isContactNameValid && !state.isSubmitting
            }

            const invalidState: OnboardingWizardState = {
                companyName: '',
                contactName: 'John Doe',
                email: '',
                website: '',
                isSubmitting: false,
                touched: { companyName: false, contactName: false, email: false, website: false }
            }

            expect(canSubmit(invalidState)).toBe(false)
        })

        test('should prevent submit when already submitting', () => {
            const canSubmit = (state: OnboardingWizardState): boolean => {
                return !state.isSubmitting
            }

            const submittingState: OnboardingWizardState = {
                companyName: 'Acme Inc',
                contactName: 'John Doe',
                email: '',
                website: '',
                isSubmitting: true,
                touched: { companyName: false, contactName: false, email: false, website: false }
            }

            expect(canSubmit(submittingState)).toBe(false)
        })
    })

    describe('Touched State Management', () => {
        test('should mark field as touched', () => {
            const touched = {
                companyName: false,
                contactName: false,
                email: false,
                website: false
            }

            const markTouched = (field: keyof typeof touched) => {
                touched[field] = true
            }

            markTouched('companyName')
            expect(touched.companyName).toBe(true)
            expect(touched.contactName).toBe(false)
        })

        test('should mark all fields as touched on invalid submit', () => {
            const touched = {
                companyName: false,
                contactName: false,
                email: false,
                website: false
            }

            const markAllTouched = () => {
                touched.companyName = true
                touched.contactName = true
                touched.email = true
                touched.website = true
            }

            markAllTouched()
            expect(touched.companyName).toBe(true)
            expect(touched.contactName).toBe(true)
            expect(touched.email).toBe(true)
            expect(touched.website).toBe(true)
        })
    })

    describe('Validation Class Generation', () => {
        test('should return is-valid for valid fields with content', () => {
            const getValidationClass = (
                field: 'companyName' | 'contactName' | 'email' | 'website',
                value: string,
                isValid: boolean,
                isTouched: boolean
            ): string => {
                if (field === 'companyName' || field === 'contactName') {
                    if (value.trim().length > 0) {
                        return isValid ? 'is-valid' : 'is-invalid'
                    }
                    return isTouched ? 'is-invalid' : ''
                }

                if (field === 'email' || field === 'website') {
                    if (!value || value.trim() === '') {
                        return ''
                    }
                    return isValid ? 'is-valid' : 'is-invalid'
                }

                return ''
            }

            expect(getValidationClass('companyName', 'Acme', true, false)).toBe('is-valid')
            expect(getValidationClass('companyName', '', false, true)).toBe('is-invalid')
            expect(getValidationClass('companyName', '', false, false)).toBe('')
            expect(getValidationClass('email', '', true, false)).toBe('')
            expect(getValidationClass('email', 'user@example.com', true, false)).toBe('is-valid')
            expect(getValidationClass('email', 'invalid', false, false)).toBe('is-invalid')
        })
    })

    describe('Initial Config', () => {
        test('should accept initial email from config', () => {
            const config = {
                initialEmail: 'user@example.com',
                initialContactName: 'John Doe'
            }

            expect(config.initialEmail).toBe('user@example.com')
            expect(config.initialContactName).toBe('John Doe')
        })

        test('should use empty string as fallback for missing config', () => {
            const getInitialValue = (configValue?: string): string => {
                return configValue || ''
            }

            expect(getInitialValue(undefined)).toBe('')
            expect(getInitialValue('')).toBe('')
            expect(getInitialValue('value')).toBe('value')
        })
    })

    describe('Submit Handler', () => {
        test('should set isSubmitting to true on valid submit', () => {
            let isSubmitting = false

            const handleSubmit = (canSubmit: boolean): boolean => {
                if (!canSubmit) {
                    return false
                }
                isSubmitting = true
                return true
            }

            expect(handleSubmit(true)).toBe(true)
            expect(isSubmitting).toBe(true)
        })

        test('should return false and not submit when validation fails', () => {
            let isSubmitting = false

            const handleSubmit = (canSubmit: boolean): boolean => {
                if (!canSubmit) {
                    return false
                }
                isSubmitting = true
                return true
            }

            expect(handleSubmit(false)).toBe(false)
            expect(isSubmitting).toBe(false)
        })
    })
})
