import { formatDate as sharedFormatDate } from '../../core/js/utils';

interface FAQ {
    id: string;
    question: string;
    answer: string;
    expanded: boolean;
}

interface DowngradeLimits {
    [planKey: string]: {
        exceeds: boolean;
        resources: string[];
    };
}

interface PlanSelectionData {
    billingPeriod: 'monthly' | 'annual';
    currentPlan: string;
    faqs: FAQ[];
    isSubmitting: boolean;
    cancelAtPeriodEnd: boolean;
    currentPeriodEnd: string;
    downgradeLimits: DowngradeLimits;

    init(): void;
    toggleFAQ(id: string): void;
    canSelectPlan(planKey?: string): boolean;
    getButtonText(planKey: string): string;
    handlePlanSelection(planKey: string): void;
    formatDate(dateStr: string): string;
    getDowngradeWarning(planKey: string): string | null;
}

export function registerPlanSelection() {
    if (window.Alpine) {
        window.Alpine.data('planSelection', planSelection);
    } else {
        console.warn('Alpine not found when registering planSelection');
    }
}

export default function planSelection(initialData: {
    currentPlan: string;
    csrfToken: string;
    enterpriseContactUrl: string;
    currentSubscriptionStatus?: string;
    portalUrl?: string | null;
    cancelAtPeriodEnd?: boolean;
    currentPeriodEnd?: string;
    downgradeLimits?: DowngradeLimits;
    billingPeriod?: 'monthly' | 'annual';
}): PlanSelectionData {
    return {
        billingPeriod: initialData.billingPeriod || 'monthly',
        currentPlan: initialData.currentPlan,
        isSubmitting: false,
        cancelAtPeriodEnd: initialData.cancelAtPeriodEnd || false,
        currentPeriodEnd: initialData.currentPeriodEnd || '',
        downgradeLimits: initialData.downgradeLimits || {},

        formatDate(dateStr: string): string {
            return sharedFormatDate(dateStr, { fallback: '' });
        },

        faqs: [
            {
                id: 'what-is-sbom',
                question: 'What is an SBOM and why do I need it?',
                answer: 'An SBOM (Software Bill of Materials) is a comprehensive inventory of all software components in your applications. It\'s essential for security, compliance, and vulnerability management.',
                expanded: false
            },
            {
                id: 'free-trial',
                question: 'Do you offer a free trial?',
                answer: 'Yes! Our Community plan is free forever. For Business plans, you get a 14-day free trial to test all premium features.',
                expanded: false
            },
            {
                id: 'upgrade-anytime',
                question: 'Can I upgrade or downgrade my plan anytime?',
                answer: 'You can change plans at any time. If your usage exceeds a plan’s limits, reduce it before downgrading. Review the billing changes before confirming.',
                expanded: false
            },
            {
                id: 'enterprise-features',
                question: 'What\'s included in the Enterprise plan?',
                answer: 'Enterprise includes unlimited everything, advanced security features, dedicated support, custom integrations, and SLA guarantees. Contact us for details.',
                expanded: false
            },
            {
                id: 'billing-period',
                question: 'How does annual billing work?',
                answer: 'The annual price is charged once a year. Choose Annual above to compare prices and see the available savings.',
                expanded: false
            }
        ],

        init() {
            // Validate downgradeLimits structure
            if (!this.downgradeLimits || typeof this.downgradeLimits !== 'object') {
                this.downgradeLimits = {};
            }
        },

        toggleFAQ(id: string) {
            const faq = this.faqs.find(f => f.id === id);
            if (faq) {
                faq.expanded = !faq.expanded;
            }
        },

        canSelectPlan(planKey?: string) {
            if (this.isSubmitting) return false;

            // If checking a specific plan, check if downgrade limits are exceeded
            if (planKey && this.downgradeLimits) {
                const limits = this.downgradeLimits[planKey];
                if (limits && limits.exceeds) {
                    return false;
                }
            }

            return planKey !== 'community' || (this.currentPlan !== 'community' && !this.cancelAtPeriodEnd);
        },

        getDowngradeWarning(planKey: string): string | null {
            if (!this.downgradeLimits || !this.downgradeLimits[planKey]) {
                return null;
            }
            const limits = this.downgradeLimits[planKey];
            if (limits && limits.exceeds && limits.resources && limits.resources.length > 0) {
                return `Reduce usage to choose this plan: ${limits.resources.join(', ')}.`;
            }
            return null;
        },

        getButtonText(planKey: string): string {
            const isSubscribed = initialData.currentSubscriptionStatus === 'active' || initialData.currentSubscriptionStatus === 'trialing';

            if (this.isSubmitting && this.currentPlan !== planKey && planKey !== 'enterprise') {
                return 'Processing...';
            }

            // Check if downgrade limits are exceeded
            if (this.downgradeLimits && this.downgradeLimits[planKey]) {
                const limits = this.downgradeLimits[planKey];
                if (limits && limits.exceeds) {
                    return 'Over plan limits';
                }
            }

            if (this.cancelAtPeriodEnd && planKey === 'community') {
                return 'Downgrade scheduled';
            }

            if (this.currentPlan === planKey) {
                if (planKey === 'enterprise') return 'Contact sales';
                // If we are canceling, "Manage subscription" (on Business) takes them to Portal to Resume
                if (planKey !== 'community') return 'Manage subscription';
                return 'Current plan';
            } else if ((!this.currentPlan || this.currentPlan === 'unknown') && planKey === 'community') {
                return 'Choose Community';
            } else if (planKey === 'enterprise') {
                return 'Contact sales';
            } else {
                if (isSubscribed && planKey === 'community') return 'Downgrade to Community';
                if (isSubscribed) return 'Select plan';
                return this.currentPlan ? 'Select plan' : 'Get started';
            }
        },

        handlePlanSelection(planKey: string) {
            if (!this.canSelectPlan(planKey)) return;

            if (planKey === 'enterprise') {
                window.location.href = initialData.enterpriseContactUrl;
                return;
            }

            const isSubscribed = initialData.currentSubscriptionStatus === 'active' || initialData.currentSubscriptionStatus === 'trialing';
            const hasPortalUrl = initialData.portalUrl && initialData.portalUrl.trim() !== '';

            // If user has an active subscription AND has a portal URL (meaning they have a Stripe customer),
            // redirect to Portal for subscription management
            // Note: subscription_status can be 'active' for community plans too (set in billing_plan_limits),
            // so we need to check if portalUrl exists to determine if they actually have a Stripe subscription
            if (isSubscribed && hasPortalUrl) {
                this.isSubmitting = true;

                // Determine flow type
                let flowType = 'subscription_update';
                if (planKey === 'community') {
                    // Downgrading to community means canceling the subscription
                    flowType = 'subscription_cancel';
                }

                // Redirect to Portal with flow type
                // hasPortalUrl check above guarantees portalUrl is not null/undefined
                const joinChar = initialData.portalUrl!.includes('?') ? '&' : '?';
                const portalUrl = `${initialData.portalUrl!}${joinChar}flow_type=${flowType}`;
                window.location.href = portalUrl;
                return;
            }

            // Legacy flow for new subscriptions or non-active users
            this.isSubmitting = true;

            const form = document.createElement('form');
            form.method = 'POST';
            form.action = '';

            const csrfInput = document.createElement('input');
            csrfInput.type = 'hidden';
            csrfInput.name = 'csrfmiddlewaretoken';
            csrfInput.value = initialData.csrfToken;
            form.appendChild(csrfInput);

            const planInput = document.createElement('input');
            planInput.type = 'hidden';
            planInput.name = 'plan';
            planInput.value = planKey;
            form.appendChild(planInput);

            const periodInput = document.createElement('input');
            periodInput.type = 'hidden';
            periodInput.name = 'billing_period';
            periodInput.value = this.billingPeriod;
            form.appendChild(periodInput);

            document.body.appendChild(form);
            form.submit();
        },


    };
}
