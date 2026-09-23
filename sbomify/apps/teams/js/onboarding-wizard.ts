import Alpine from 'alpinejs';
import type { AlpineComponent } from 'alpinejs';

interface OnboardingWizardConfig {
    step: 'organisation' | 'security';
    addressExpanded: boolean;
}

interface OnboardingWizard {
    step: 'organisation' | 'security';
    addressExpanded: boolean;
    isSubmitting: boolean;
    validate(step: 'organisation' | 'security'): boolean;
    focusStep(): void;
    next(): void;
    back(): void;
    submit(event: SubmitEvent): void;
}

/** Keep both steps in one form so Back and validation never discard an answer. */
export function onboardingWizard(config: OnboardingWizardConfig): AlpineComponent<OnboardingWizard> {
    return {
        step: config.step,
        addressExpanded: config.addressExpanded,
        isSubmitting: false,

        validate(step) {
            const fields = this.$refs[step].querySelectorAll<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>(
                'input, select, textarea'
            );
            const invalid = Array.from(fields).find(field => !field.disabled && !field.checkValidity());
            if (!invalid) return true;
            this.step = step;
            this.$nextTick(() => invalid.reportValidity());
            return false;
        },

        focusStep() {
            this.$nextTick(() => {
                const title = this.$refs[`${this.step}Title`];
                title.focus({ preventScroll: true });
                title.scrollIntoView({ block: 'start' });
            });
        },

        next() {
            if (!this.validate('organisation')) return;
            const email = this.$refs.email as HTMLInputElement;
            const securityEmail = this.$refs.securityEmail as HTMLInputElement;
            if (!securityEmail.value) securityEmail.value = email.value;
            this.step = 'security';
            this.focusStep();
        },

        back() {
            this.step = 'organisation';
            this.focusStep();
        },

        submit(event) {
            if (this.step === 'organisation') {
                event.preventDefault();
                this.next();
                return;
            }
            if (this.isSubmitting || !this.validate('organisation') || !this.validate('security')) {
                event.preventDefault();
                return;
            }
            this.isSubmitting = true;
        },
    };
}

export function registerOnboardingWizard(): void {
    Alpine.data('onboardingWizard', onboardingWizard);
}
