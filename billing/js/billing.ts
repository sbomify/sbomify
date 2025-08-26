import { showSuccess, showError } from '../../core/js/alerts';

/**
 * Initialize billing toggle functionality for plan selection page
 */
function initializeBillingToggle(): void {
    const billingToggle = document.getElementById('billingToggle') as HTMLInputElement | null;
    const monthlyLabel = document.getElementById('monthlyLabel') as HTMLElement | null;
    const annualLabel = document.getElementById('annualLabel') as HTMLElement | null;
    const businessPrice = document.getElementById('businessPrice') as HTMLElement | null;
    const businessNote = document.getElementById('businessNote') as HTMLElement | null;
    const businessBillingPeriod = document.getElementById('businessBillingPeriod') as HTMLInputElement | null;

    if (!billingToggle) return;

    billingToggle.addEventListener('change', function() {
        const isAnnual = this.checked;

        // Update labels
        if (monthlyLabel) monthlyLabel.classList.toggle('active', !isAnnual);
        if (annualLabel) annualLabel.classList.toggle('active', isAnnual);

        // Update business pricing
        if (businessPrice) {
            businessPrice.textContent = isAnnual ? '$159' : '$199';
        }

        if (businessNote) {
            businessNote.style.display = isAnnual ? 'block' : 'none';
        }

        if (businessBillingPeriod) {
            businessBillingPeriod.value = isAnnual ? 'annual' : 'monthly';
        }
    });
}

/**
 * Initialize community downgrade popover functionality
 */
function initializeCommunityDowngradePopover(): void {
    const communityDowngradeBtn = document.getElementById('communityDowngradeBtn') as HTMLElement | null;
    if (!communityDowngradeBtn) return;

    const popoverContent = document.getElementById('communityDowngradePopover');
    if (!popoverContent) return;

    // Initialize popover with hidden content
    const popover = new window.bootstrap.Popover(communityDowngradeBtn, {
        html: true,
        trigger: 'click',
        placement: 'top',
        content: popoverContent.innerHTML
    });

    // Add event listeners for popover buttons after popover is shown
    communityDowngradeBtn.addEventListener('shown.bs.popover', () => {
        const cancelBtn = document.getElementById('cancelDowngrade') as HTMLButtonElement | null;
        const confirmBtn = document.getElementById('confirmDowngrade') as HTMLButtonElement | null;

        if (cancelBtn) {
            cancelBtn.addEventListener('click', () => {
                popover.hide();
            });
        }

        if (confirmBtn) {
            confirmBtn.addEventListener('click', () => {
                popover.hide();
                const form = document.getElementById('communityPlanForm') as HTMLFormElement | null;
                if (form) {
                    form.submit();
                }
            });
        }
    });
}

/**
 * Initialize FAQ toggle functionality
 */
function initializeFAQToggle(): void {
    const faqQuestions = document.querySelectorAll('.faq-question') as NodeListOf<HTMLElement>;

    faqQuestions.forEach(question => {
        question.addEventListener('click', () => {
            const id = question.getAttribute('data-id');
            if (id) {
                toggleFAQ(id);
            }
        });
    });
}

/**
 * Toggle FAQ answer visibility
 */
function toggleFAQ(id: string): void {
    const answer = document.getElementById(`answer-${id}`) as HTMLElement | null;
    const icon = document.getElementById(`icon-${id}`) as HTMLElement | null;

    if (answer && icon) {
        const isVisible = answer.style.display !== 'none';
        answer.style.display = isVisible ? 'none' : 'block';
        icon.classList.toggle('rotated', !isVisible);
    }
}

// Initialize billing notifications
document.addEventListener('DOMContentLoaded', () => {
    // Check for flash messages in the DOM
    const messages = document.querySelectorAll('[data-flash-message]');
    messages.forEach(messageElement => {
        const message = messageElement.textContent;
        const type = messageElement.getAttribute('data-message-type');

        if (type === 'error') {
            showError(message || '');
        } else {
            showSuccess(message || '');
        }

        // Remove the message element
        messageElement.remove();
    });

    // Initialize plan selection page functionality
    initializeBillingToggle();
    initializeCommunityDowngradePopover();
    initializeFAQToggle();
});