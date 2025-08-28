/**
 * Getting Started Wizard TypeScript Module
 * Handles all interactive functionality for the wizard
 */

import { showConfirmation } from '../../core/js/alerts';

export class GettingStartedWizard {
    private form: HTMLFormElement | null = null;
    private progressBar: HTMLElement | null = null;
    private skipButton: HTMLButtonElement | null = null;
    private previousButton: HTMLButtonElement | null = null;
    private currentStep: string = '';

    // Step flow mapping
    private readonly stepFlow = ['plan', 'product', 'project', 'component', 'complete'];

    constructor() {
        this.init();
    }

    private init(): void {
        // Wait for DOM to be ready
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', () => this.setupElements());
        } else {
            this.setupElements();
        }
    }

    private setupElements(): void {
        // Get wizard elements
        this.form = document.querySelector('.wizard-form-modern');
        this.progressBar = document.querySelector('.wizard-progress-bar');
        this.skipButton = document.querySelector('[data-wizard-skip]');
        this.previousButton = document.querySelector('[data-wizard-previous]');

        // Get current step from page data
        this.getCurrentStep();

        // Setup event listeners
        this.setupFormSubmission();
        this.setupSkipConfirmation();
        this.setupPreviousButton();
        this.animateProgressBar();
        this.autoFocusFirstInput();
    }

    private getCurrentStep(): void {
        // Try to get current step from various sources
        const stepElement = document.querySelector('[data-current-step]');
        if (stepElement) {
            this.currentStep = stepElement.getAttribute('data-current-step') || '';
        } else {
            // Fallback: parse from URL or other indicators
            const urlParams = new URLSearchParams(window.location.search);
            this.currentStep = urlParams.get('step') || 'plan';
        }
    }

    private setupFormSubmission(): void {
        if (!this.form) return;

        this.form.addEventListener('submit', (e) => {
            // Check if enterprise plan is selected on plan step
            if (this.currentStep === 'plan') {
                const enterpriseRadio = this.form?.querySelector('input[name="plan"][value="enterprise"]') as HTMLInputElement | null;
                if (enterpriseRadio && enterpriseRadio.checked) {
                    e.preventDefault(); // Prevent normal form submission

                    // Show loading state for enterprise redirect
                    const submitBtn = this.form?.querySelector('button[type="submit"]') as HTMLButtonElement;
                    if (submitBtn) {
                        submitBtn.disabled = true;
                        submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>Redirecting to contact form...';
                    }

                    // Redirect to enterprise contact form
                    window.location.href = '/enterprise-contact/';
                    return;
                }
            }

            const submitBtn = this.form?.querySelector('.wizard-submit-btn') as HTMLButtonElement;
            if (!submitBtn) return;

            const originalText = submitBtn.innerHTML;

            // Show loading state
            submitBtn.disabled = true;
            submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>Processing...';

            // Reset if form submission fails (timeout safety)
            setTimeout(() => {
                if (submitBtn.disabled) {
                    submitBtn.disabled = false;
                    submitBtn.innerHTML = originalText;
                }
            }, 10000); // 10 second timeout
        });
    }

    private setupSkipConfirmation(): void {
        if (!this.skipButton) return;

        this.skipButton.addEventListener('click', async (e) => {
            e.preventDefault();

            const confirmed = await showConfirmation({
                title: 'Skip Getting Started Wizard?',
                message: 'Are you sure you want to skip the getting started wizard? You can always create products and components later from the dashboard.',
                confirmButtonText: 'Yes, skip for now',
                cancelButtonText: 'Continue wizard'
            });

            if (confirmed) {
                // If confirmed, submit the form
                const form = this.skipButton?.closest('form') as HTMLFormElement;
                if (form) {
                    form.submit();
                }
            }
        });
    }

    private setupPreviousButton(): void {
        if (!this.previousButton) return;

        this.previousButton.addEventListener('click', () => {
            this.navigateToPreviousStep();
        });
    }

    private navigateToPreviousStep(): void {
        const currentIndex = this.stepFlow.indexOf(this.currentStep);
        if (currentIndex > 0) {
            const previousStep = this.stepFlow[currentIndex - 1];
            this.navigateToStep(previousStep);
        }
    }

    private navigateToStep(step: string): void {
        // Navigate to the specified wizard step
        const wizardUrl = new URL('/workspace/getting-started/', window.location.origin);
        wizardUrl.searchParams.set('step', step);
        window.location.href = wizardUrl.toString();
    }

    private animateProgressBar(): void {
        if (!this.progressBar) return;

        // Get the target width from the data attribute
        const progress = this.progressBar.dataset.progress;
        if (!progress) return;

        const targetWidth = `${progress}%`;

        // Start from 0 and animate to target
        this.progressBar.style.width = '0%';

        // Small delay for smooth animation
        setTimeout(() => {
            if (this.progressBar) {
                this.progressBar.style.width = targetWidth;
            }
        }, 300);
    }

    private autoFocusFirstInput(): void {
        // Auto-focus first non-radio input after a short delay
        const firstInput = document.querySelector('input:not([type="radio"]), textarea') as HTMLInputElement;
        if (firstInput) {
            setTimeout(() => {
                firstInput.focus();
            }, 500);
        }
    }
}

// Initialize the wizard when the script loads
new GettingStartedWizard();
