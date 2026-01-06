interface Usage {
    users: number;
    products: number;
    projects: number;
    components: number;
}

interface FAQ {
    id: string;
    question: string;
    answer: string;
    expanded: boolean;
}

interface Feature {
    key: string;
    label: string;
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
    teamKey: string;
    usage: Usage;
    faqs: FAQ[];
    isSubmitting: boolean;
    cancelAtPeriodEnd: boolean;
    currentPeriodEnd: string;
    downgradeLimits: DowngradeLimits;

    init(): void;
    getFeatures(planKey: string): Feature[];
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
    teamKey: string;
    usage: Usage;
    csrfToken: string;
    enterpriseContactUrl: string;
    currentSubscriptionStatus?: string;
    portalUrl?: string | null;
    cancelAtPeriodEnd?: boolean;
    currentPeriodEnd?: string;
    downgradeLimits?: DowngradeLimits;
}): PlanSelectionData {
    return {
        billingPeriod: 'monthly',
        currentPlan: initialData.currentPlan,
        teamKey: initialData.teamKey,
        usage: initialData.usage,
        isSubmitting: false,
        cancelAtPeriodEnd: initialData.cancelAtPeriodEnd || false,
        currentPeriodEnd: initialData.currentPeriodEnd || '',
        downgradeLimits: initialData.downgradeLimits || {},

        formatDate(dateStr: string): string {
            if (!dateStr) return '';
            return new Date(dateStr).toLocaleDateString(undefined, {
                year: 'numeric', month: 'short', day: 'numeric'
            });
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
                answer: 'Absolutely! You can upgrade or downgrade your plan at any time. Changes take effect immediately, and billing adjustments are prorated.',
                expanded: false
            },
            {
                id: 'enterprise-features',
                question: 'What\'s included in the Enterprise plan?',
                answer: 'Enterprise includes unlimited everything, advanced security features, dedicated support, custom integrations, and SLA guarantees. Contact us for details.',
                expanded: false
            },
            {
                id: 'data-security',
                question: 'How secure is my data?',
                answer: 'We use enterprise-grade security with end-to-end encryption and regular security audits. Your data is always protected.',
                expanded: false
            }
        ],

        init() {
            console.log('planSelection init:', {
                currentPlan: this.currentPlan,
                cancelAtPeriodEnd: this.cancelAtPeriodEnd,
                currentPeriodEnd: this.currentPeriodEnd,
                currentSubscriptionStatus: initialData.currentSubscriptionStatus,
                downgradeLimits: this.downgradeLimits,
            });
            
            // Validate downgradeLimits structure
            if (!this.downgradeLimits || typeof this.downgradeLimits !== 'object') {
                console.warn('downgradeLimits is missing or invalid, initializing empty object');
                this.downgradeLimits = {};
            }
        },

        getFeatures(planKey: string) {
            const baseFeatures: Feature[] = [
                { key: 'unlimited-sboms', label: 'Unlimited SBOMs' },
                { key: 'unlimited-products', label: 'Unlimited products' },
                { key: 'unlimited-projects', label: 'Unlimited projects' },
                { key: 'unlimited-components', label: 'Unlimited components' },
            ];

            if (planKey === 'community') {
                baseFeatures.push(
                    { key: 'user-limit', label: '1 user (owner only)' },
                    { key: 'public-only', label: 'All data is public' },
                    { key: 'vulnerability-scanning', label: 'Weekly vulnerability scans' },
                    { key: 'community-support', label: 'Community support' },
                    { key: 'api-access', label: 'API access' }
                );
            } else if (planKey === 'business') {
                baseFeatures.push(
                    { key: 'includes-community', label: 'Everything in Community, plus:' },
                    { key: 'user-limit', label: 'Up to 5 users' },
                    { key: 'private-data', label: 'Private components/projects/products' },
                    { key: 'ntia-compliance', label: 'NTIA Minimum Elements check' },
                    { key: 'vulnerability-scanning', label: 'Advanced vulnerability scanning (every 12 hours)' },
                    { key: 'product-identifiers', label: 'Product identifiers (SKUs/barcodes)' },
                    { key: 'priority-support', label: 'Priority support' },
                    { key: 'team-management', label: 'Workspace management' }
                );
            } else if (planKey === 'enterprise') {
                baseFeatures.push(
                    { key: 'includes-business', label: 'Everything in Business, plus:' },
                    { key: 'user-limit', label: 'Unlimited users' },
                    { key: 'custom-dt-servers', label: 'Custom Dependency Track servers' },
                    { key: 'dedicated-support', label: 'Dedicated support' },
                    { key: 'custom-integrations', label: 'Custom integrations' },
                    { key: 'sla-guarantee', label: 'SLA guarantee' },
                    { key: 'advanced-security', label: 'Advanced security' },
                    { key: 'custom-deployment', label: 'Custom deployment options' }
                );
            }

            return baseFeatures;
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
            
            // Allow all plans to be clickable - we handle special cases in handlePlanSelection
            return true;
        },
        
        getDowngradeWarning(planKey: string): string | null {
            if (!this.downgradeLimits || !this.downgradeLimits[planKey]) {
                return null;
            }
            const limits = this.downgradeLimits[planKey];
            if (limits && limits.exceeds && limits.resources && limits.resources.length > 0) {
                return `Cannot downgrade: You currently have ${limits.resources.join(', ')}. Please reduce your usage to downgrade to this plan.`;
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
                    return 'Cannot Downgrade';
                }
            }

            if (this.cancelAtPeriodEnd && planKey === 'community') {
                return 'Downgrade Scheduled';
            }

            if (this.currentPlan === planKey) {
                if (planKey === 'enterprise') return 'Contact Sales';
                // If we are canceling, "Manage Subscription" (on Business) takes them to Portal to Resume
                if (planKey !== 'community') return 'Manage Subscription';
                return 'Current Plan';
            } else if ((!this.currentPlan || this.currentPlan === 'unknown') && planKey === 'community') {
                return 'Get Started with Community';
            } else if (planKey === 'enterprise') {
                return 'Contact Sales';
            } else {
                if (isSubscribed && planKey === 'community') return 'Downgrade to Community';
                if (isSubscribed) return 'Switch to This Plan';
                return this.currentPlan ? 'Switch to This Plan' : 'Get Started';
            }
        },

        handlePlanSelection(planKey: string) {
            console.log('handlePlanSelection called:', { planKey, isSubmitting: this.isSubmitting });
            
            if (this.isSubmitting) {
                console.log('Already submitting, returning');
                return;
            }

            // Check if downgrade limits are exceeded
            if (this.downgradeLimits && this.downgradeLimits[planKey]) {
                const limits = this.downgradeLimits[planKey];
                if (limits && limits.exceeds) {
                    const warning = this.getDowngradeWarning(planKey);
                    if (warning) {
                        alert(warning);
                    }
                    return;
                }
            }

            // Handle clicking Community when downgrade is already scheduled
            if (this.cancelAtPeriodEnd && planKey === 'community') {
                const endDate = this.formatDate(this.currentPeriodEnd);
                alert(`Your downgrade to Community is already scheduled. Your current plan will remain active until ${endDate || 'the end of your billing period'}.`);
                return;
            }

            if (planKey === 'enterprise') {
                window.location.href = initialData.enterpriseContactUrl;
                return;
            }

            const isSubscribed = initialData.currentSubscriptionStatus === 'active' || initialData.currentSubscriptionStatus === 'trialing';
            const hasPortalUrl = initialData.portalUrl && initialData.portalUrl.trim() !== '';
            console.log('Subscription check:', { isSubscribed, status: initialData.currentSubscriptionStatus, portalUrl: initialData.portalUrl, hasPortalUrl });

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
                console.log('Redirecting to portal:', portalUrl);
                window.location.href = portalUrl;
                return;
            }

            // Legacy flow for new subscriptions or non-active users
            console.log('Using form submission flow');
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
            console.log('Form created, submitting:', { plan: planKey, period: this.billingPeriod });

            try {
                form.submit();
            } catch (error) {
                console.error('Form submission failed:', error);
                this.isSubmitting = false;
                if (document.body.contains(form)) {
                    document.body.removeChild(form);
                }
            }
        },


    };
}
