import Alpine from 'alpinejs';

/**
 * Configuration for the onboarding wizard Alpine.js component.
 */
interface OnboardingWizardConfig {
    /** Initial email value (pre-filled from user's email) */
    initialEmail: string;
    /** Initial contact name value (pre-filled from user's full name) */
    initialContactName: string;
}

/**
 * Registers the Alpine.js 'onboardingWizard' component for the SBOM Identity setup form.
 * Handles real-time validation, form state, and loading states.
 */
export function registerOnboardingWizard() {
    Alpine.data('onboardingWizard', (config: OnboardingWizardConfig) => ({
        companyName: '',
        contactName: config.initialContactName || '',
        email: config.initialEmail || '',
        website: '',
        isSubmitting: false,
        touched: {
            companyName: false,
            contactName: false,
            email: false,
            website: false,
        },

        /**
         * Check if company name is valid (non-empty after trim).
         */
        get isCompanyValid(): boolean {
            return this.companyName.trim().length > 0;
        },

        /**
         * Check if contact name is valid (non-empty after trim).
         */
        get isContactNameValid(): boolean {
            return this.contactName.trim().length > 0;
        },

        /**
         * Check if email is valid (empty or valid format).
         * Email is optional, so empty is valid.
         */
        get isEmailValid(): boolean {
            if (!this.email || this.email.trim() === '') {
                return true;
            }
            const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
            return emailRegex.test(this.email.trim());
        },

        /**
         * Check if website URL is valid (empty or valid URL format).
         * Website is optional, so empty is valid.
         */
        get isWebsiteValid(): boolean {
            if (!this.website || this.website.trim() === '') {
                return true;
            }
            try {
                new URL(this.website.trim());
                return true;
            } catch {
                return false;
            }
        },

        /**
         * Check if form can be submitted.
         */
        get canSubmit(): boolean {
            return (
                this.isCompanyValid &&
                this.isContactNameValid &&
                this.isEmailValid &&
                this.isWebsiteValid &&
                !this.isSubmitting
            );
        },

        /**
         * Mark a field as touched (for showing validation errors).
         */
        markTouched(field: 'companyName' | 'contactName' | 'email' | 'website') {
            this.touched[field] = true;
        },

        /**
         * Get validation state class for a field.
         * Returns 'is-valid' if valid and has content, 'is-invalid' if touched and invalid.
         */
        getValidationClass(field: 'companyName' | 'contactName' | 'email' | 'website'): string {
            if (field === 'companyName') {
                if (this.companyName.trim().length > 0) {
                    return this.isCompanyValid ? 'is-valid' : 'is-invalid';
                }
                return this.touched.companyName ? 'is-invalid' : '';
            }

            if (field === 'contactName') {
                if (this.contactName.trim().length > 0) {
                    return this.isContactNameValid ? 'is-valid' : 'is-invalid';
                }
                return this.touched.contactName ? 'is-invalid' : '';
            }

            if (field === 'email') {
                if (!this.email || this.email.trim() === '') {
                    return ''; // Optional field, no validation state when empty
                }
                return this.isEmailValid ? 'is-valid' : 'is-invalid';
            }

            if (field === 'website') {
                if (!this.website || this.website.trim() === '') {
                    return ''; // Optional field, no validation state when empty
                }
                return this.isWebsiteValid ? 'is-valid' : 'is-invalid';
            }

            return '';
        },

        /**
         * Handle form submission - set loading state.
         */
        handleSubmit() {
            if (!this.canSubmit) {
                // Mark all fields as touched to show validation errors
                this.touched.companyName = true;
                this.touched.contactName = true;
                this.touched.email = true;
                this.touched.website = true;
                return false;
            }
            this.isSubmitting = true;
            return true;
        },
    }));
}

