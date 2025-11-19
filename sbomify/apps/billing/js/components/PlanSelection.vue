<template>
  <div class="pricing-page">
    <!-- Hero Section -->
    <section class="hero-section py-5">
      <div class="container">
        <div class="row justify-content-center text-center">
          <div class="col-lg-8">
            <h1 class="hero-title mb-4">Choose the Perfect Plan for Your Workspace</h1>
                         <p class="hero-subtitle mb-4">
               Secure, scalable security and product artifact management for workspaces of all sizes. Start with Community, upgrade when you need more.
             </p>
            <div class="billing-toggle-wrapper mb-5">
              <div class="billing-toggle">
                <span class="toggle-label" :class="{ active: billingPeriod === 'monthly' }">Monthly</span>
                                <label class="toggle-switch">
                  <input
                    type="checkbox"
                    :checked="billingPeriod === 'annual'"
                    @change="billingPeriod = ($event.target as HTMLInputElement)?.checked ? 'annual' : 'monthly'"
                  >
                  <span class="toggle-slider"></span>
                </label>
                <span class="toggle-label" :class="{ active: billingPeriod === 'annual' }">
                  Annual
                  <span class="savings-badge">Save 20%</span>
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- Current Usage Section -->
    <section v-if="usage.users > 0 || usage.products > 0 || usage.projects > 0 || usage.components > 0" class="usage-section py-4">
      <div class="container">
        <div class="row justify-content-center">
          <div class="col-lg-8">
            <div class="usage-card">
              <div class="usage-header">
                <h3 class="usage-title">
                  <i class="fas fa-chart-bar me-2"></i>
                  Current Usage
                </h3>
              </div>
                             <div class="usage-stats">
                 <div class="usage-stat">
                   <span class="stat-number">{{ usage.users || 0 }}</span>
                   <span class="stat-label">Users</span>
                 </div>
                 <div class="usage-stat">
                   <span class="stat-number">{{ usage.products }}</span>
                   <span class="stat-label">Products</span>
                 </div>
                 <div class="usage-stat">
                   <span class="stat-number">{{ usage.projects }}</span>
                   <span class="stat-label">Projects</span>
                 </div>
                 <div class="usage-stat">
                   <span class="stat-number">{{ usage.components }}</span>
                   <span class="stat-label">Components</span>
                 </div>
               </div>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- Pricing Cards Section -->
    <section class="pricing-section py-5">
      <div class="container">
        <div class="row justify-content-center">
                    <div v-for="planKey in ['community', 'business', 'enterprise']" :key="planKey" class="col-lg-4 col-md-6 mb-4">
            <div v-if="getPlan(planKey)" class="pricing-card" :class="{
              'current-plan': isCurrentPlan(getPlan(planKey)!),
              'popular': planKey === 'business',
              'enterprise': planKey === 'enterprise'
            }">
              <!-- Popular Badge -->
              <div v-if="planKey === 'business'" class="popular-badge">
                <i class="fas fa-star me-1"></i>
                Most Popular
              </div>

              <!-- Plan Header -->
              <div class="plan-header">
                <h3 class="plan-name">{{ getPlan(planKey)!.name }}</h3>
                <div class="plan-price">
                  <template v-if="planKey === 'community'">
                    <span class="price-main">$0</span>
                    <span class="price-period">forever</span>
                  </template>
                  <template v-else-if="planKey === 'business'">
                    <span class="price-main">${{ billingPeriod === 'monthly' ? '199' : '159' }}</span>
                    <span class="price-period">/month</span>
                    <div v-if="billingPeriod === 'annual'" class="billing-note">
                      <span class="original-price">$199/mo</span>
                      <span class="savings">Save $480/year</span>
                    </div>
                  </template>
                  <template v-else>
                    <span class="price-main">Custom</span>
                    <span class="price-period">pricing</span>
                  </template>
                </div>
                                 <p class="plan-description">{{ getPlan(planKey)!.description }}</p>
               </div>

               <!-- Features List -->
               <div class="plan-features">
                 <ul class="features-list">
                   <li v-for="feature in getFeatures(planKey)" :key="feature.key"
                       class="feature-item"
                       :class="{ 'feature-item-header': feature.key.startsWith('includes-') }">
                     <i v-if="!feature.key.startsWith('includes-')" class="fas fa-check feature-check"></i>
                     <span :class="{ 'feature-includes': feature.key.startsWith('includes-') }">{{ feature.label }}</span>
                   </li>
                 </ul>
               </div>

               <!-- Action Button -->
               <div class="plan-action">
                 <button
                   class="btn-plan"
                   :class="{
                     'btn-current': isCurrentPlan(getPlan(planKey)!),
                     'btn-primary': !isCurrentPlan(getPlan(planKey)!) && planKey !== 'enterprise',
                     'btn-enterprise': planKey === 'enterprise'
                   }"
                   :disabled="!canSelectPlan(getPlan(planKey)!)"
                   @click="handlePlanSelection(getPlan(planKey)!)"
                 >
                   {{ getButtonText(getPlan(planKey)!) }}
                 </button>

                 <!-- Warning Message -->
                 <div v-if="!canDowngrade(getPlan(planKey)!).can" class="warning-message">
                   <i class="fas fa-exclamation-triangle me-1"></i>
                   {{ canDowngrade(getPlan(planKey)!).message }}
                 </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>



    <!-- FAQ Section -->
    <section class="faq-section py-5">
      <div class="container">
        <div class="row justify-content-center">
          <div class="col-lg-8">
            <div class="faq-header text-center mb-5">
              <h2>Frequently Asked Questions</h2>
            </div>

            <div class="faq-list">
              <div v-for="faq in getFAQs()" :key="faq.id" class="faq-item">
                <div class="faq-question" @click="toggleFAQ(faq.id)">
                  <span>{{ faq.question }}</span>
                  <i class="fas fa-chevron-down" :class="{ 'rotated': faq.expanded }"></i>
                </div>
                <div v-if="faq.expanded" class="faq-answer">
                  <p>{{ faq.answer }}</p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, reactive } from 'vue';
import $axios from '../../../core/js/utils';
import { showSuccess, showError, showConfirmation } from '../../../core/js/alerts';
import { AxiosError } from 'axios';

interface Plan {
  key: string;
  name: string;
  description: string;
  max_products: number | null;
  max_projects: number | null;
  max_components: number | null;
  max_users: number | null;
}

interface Usage {
  users: number;
  products: number;
  projects: number;
  components: number;
  current_plan: string | null;
}

interface PlanFeature {
  key: string;
  label: string;
}

interface FAQ {
  id: string;
  question: string;
  answer: string;
  expanded: boolean;
}

const props = defineProps<{
  initialTeamKey?: string;
}>();

const emit = defineEmits(['plan-selected']);

const plans = ref<Plan[]>([]);
const usage = ref<Usage>({ users: 0, products: 0, projects: 0, components: 0, current_plan: null });
const currentPlan = ref<string | null>(null);
const billingPeriod = ref('monthly');

const faqs = reactive<FAQ[]>([
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
]);

const getPlan = (key: string): Plan | undefined => {
  return plans.value.find(p => p.key === key);
};

const getFeatures = (planKey: string): PlanFeature[] => {
  const baseFeatures: PlanFeature[] = [
    { key: 'unlimited-sboms', label: 'Unlimited SBOMs' },
    { key: 'unlimited-products', label: 'Unlimited products' },
    { key: 'unlimited-projects', label: 'Unlimited projects' },
    { key: 'unlimited-components', label: 'Unlimited components' },
  ];

  // Add plan-specific features
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
};

const getFAQs = () => faqs;

const toggleFAQ = (id: string) => {
  const faq = faqs.find(f => f.id === id);
  if (faq) {
    faq.expanded = !faq.expanded;
  }
};

const canDowngrade = (plan: Plan | undefined) => {
  if (!plan) {
    return { can: false, message: 'Plan not found' };
  }

  if (plan.key === currentPlan.value) {
    return { can: true, message: '' };
  }

  const currentPlanData = plans.value.find(p => p.key === currentPlan.value);
  if (!currentPlanData || (currentPlanData.max_products && !plan.max_products)) {
    return { can: true, message: '' };
  }

  if (!plan.max_products && !plan.max_projects && !plan.max_components && !plan.max_users) {
    return { can: true, message: '' };
  }

  if (plan.max_products && usage.value.products > plan.max_products) {
    return { can: false, message: `You have ${usage.value.products} products, but this plan only allows ${plan.max_products}` };
  }

  if (plan.max_projects && usage.value.projects > plan.max_projects) {
    return { can: false, message: `You have ${usage.value.projects} projects, but this plan only allows ${plan.max_projects}` };
  }

  if (plan.max_components && usage.value.components > plan.max_components) {
    return { can: false, message: `You have ${usage.value.components} components, but this plan only allows ${plan.max_components}` };
  }

  if (plan.max_users && usage.value.users > plan.max_users) {
    return { can: false, message: `You have ${usage.value.users} users, but this plan only allows ${plan.max_users}` };
  }

  return { can: true, message: '' };
};

const canSelectPlan = (plan: Plan | undefined): boolean => {
  return canDowngrade(plan).can;
};

const isCurrentPlan = (plan: Plan | undefined): boolean => {
  return plan?.key === currentPlan.value;
};

const getButtonText = (plan: Plan | undefined): string => {
  if (!plan) {
    return 'Plan Not Available';
  }

  if (plan.key === currentPlan.value) {
    return 'Current Plan';
  } else if (!currentPlan.value && plan.key === 'community') {
    return 'Get Started with Community';
  } else if (plan.key === 'enterprise') {
    return 'Contact Sales';
  } else {
    return currentPlan.value ? 'Switch to This Plan' : 'Get Started';
  }
};

async function handlePlanSelection(plan: Plan | undefined) {
  if (!plan) {
    showError('Plan not available');
    return;
  }

  try {
    if (plan.key === 'enterprise') {
      window.location.href = '/enterprise-contact/';
      return;
    }

    if (plan.key === 'community' && currentPlan.value && currentPlan.value !== 'community') {
      const confirmed = await showConfirmation({
        title: 'Confirm Downgrade',
        message: 'Are you sure you want to downgrade to the Community plan? All your SBOMs will become public and your subscription will be cancelled.',
        confirmButtonText: 'Yes, downgrade',
        cancelButtonText: 'Cancel',
        type: 'warning'
      });

      if (!confirmed) return;
    }

    const response = await $axios.post('/api/v1/billing/change-plan/', {
      plan: plan.key,
      billing_period: plan.key === 'business' ? billingPeriod.value : null,
      team_key: props.initialTeamKey
    });

    if (response.data.redirect_url) {
      window.location.href = response.data.redirect_url;
    } else {
      showSuccess('Plan updated successfully');
      emit('plan-selected');
    }
  } catch (error) {
    if (error instanceof AxiosError) {
      showError(error.response?.data?.detail || 'Failed to change plan');
    } else {
      showError('Failed to change plan');
    }
    console.error('Error changing plan:', error);
  }
}

onMounted(async () => {
  try {
    const [plansResponse, usageResponse] = await Promise.all([
      $axios.get('/api/v1/billing/plans/'),
      $axios.get('/api/v1/billing/usage/', {
        params: props.initialTeamKey ? { team_key: props.initialTeamKey } : undefined
      })
    ]);
    plans.value = plansResponse.data;
    usage.value = usageResponse.data;
    currentPlan.value = usageResponse.data.current_plan;
  } catch (error) {
    console.error('Failed to load billing data:', error);
  }
});
</script>

<style scoped>
.pricing-page {
  min-height: 100vh;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: #333;
}

/* Hero Section */
.hero-section {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  margin-bottom: 0;
}

.hero-title {
  font-size: 3rem;
  font-weight: 700;
  margin-bottom: 1.5rem;
  color: white !important;
  text-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
}

.hero-subtitle {
  font-size: 1.25rem;
  color: rgba(255, 255, 255, 0.95) !important;
  line-height: 1.6;
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.1);
}

/* Billing Toggle */
.billing-toggle-wrapper {
  display: flex;
  justify-content: center;
}

.billing-toggle {
  display: flex;
  align-items: center;
  gap: 1rem;
  background: rgba(255, 255, 255, 0.1);
  padding: 0.5rem 1.5rem;
  border-radius: 50px;
  backdrop-filter: blur(10px);
}

.toggle-label {
  font-weight: 600;
  opacity: 0.7;
  transition: opacity 0.3s ease;
}

.toggle-label.active {
  opacity: 1;
}

.toggle-switch {
  position: relative;
  width: 60px;
  height: 30px;
}

.toggle-switch input {
  opacity: 0;
  width: 0;
  height: 0;
}

.toggle-slider {
  position: absolute;
  cursor: pointer;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-color: rgba(255, 255, 255, 0.3);
  border-radius: 30px;
  transition: 0.4s;
}

.toggle-slider:before {
  position: absolute;
  content: "";
  height: 22px;
  width: 22px;
  left: 4px;
  bottom: 4px;
  background-color: white;
  border-radius: 50%;
  transition: 0.4s;
}

input:checked + .toggle-slider {
  background-color: rgba(255, 255, 255, 0.5);
}

input:checked + .toggle-slider:before {
  transform: translateX(30px);
}

.savings-badge {
  background: #10b981;
  color: white;
  padding: 0.25rem 0.5rem;
  border-radius: 12px;
  font-size: 0.75rem;
  font-weight: 600;
  margin-left: 0.5rem;
}

/* Usage Section */
.usage-section {
  background: white;
  border-bottom: 1px solid #e2e8f0;
}

.usage-card {
  background: white;
  border-radius: 16px;
  padding: 2rem;
  box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
  border: 1px solid #e2e8f0;
}

.usage-header {
  text-align: center;
  margin-bottom: 2rem;
}

.usage-title {
  font-size: 1.5rem;
  font-weight: 600;
  color: #1f2937;
  margin: 0;
}

.usage-stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 2rem;
  text-align: center;
}

.usage-stat {
  display: flex;
  flex-direction: column;
  align-items: center;
}

.stat-number {
  font-size: 2.5rem;
  font-weight: 700;
  color: #667eea;
  line-height: 1;
}

.stat-label {
  font-size: 0.875rem;
  font-weight: 500;
  color: #6b7280;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin-top: 0.5rem;
}

/* Pricing Section */
.pricing-section {
  background: white;
  padding: 4rem 0;
}

.pricing-card {
  background: white;
  border-radius: 16px;
  padding: 2rem;
  box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
  border: 2px solid #e2e8f0;
  position: relative;
  transition: all 0.3s ease;
  height: 100%;
  display: flex;
  flex-direction: column;
}

.pricing-card:hover {
  transform: translateY(-4px);
  box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1);
}

.pricing-card.popular {
  border-color: #667eea;
  transform: scale(1.05);
}

.pricing-card.popular:hover {
  transform: scale(1.05) translateY(-4px);
}

.pricing-card.current-plan {
  border-color: #10b981;
  background: linear-gradient(135deg, #f0fdf4 0%, #dcfce7 100%);
}

.pricing-card.enterprise {
  border-color: #8b5cf6;
  background: linear-gradient(135deg, #faf5ff 0%, #f3e8ff 100%);
}

.popular-badge {
  position: absolute;
  top: -12px;
  left: 50%;
  transform: translateX(-50%);
  background: #667eea;
  color: white;
  padding: 0.5rem 1rem;
  border-radius: 20px;
  font-size: 0.875rem;
  font-weight: 600;
  white-space: nowrap;
}

.plan-header {
  text-align: center;
  margin-bottom: 2rem;
}

.plan-name {
  font-size: 1.5rem;
  font-weight: 700;
  color: #1f2937;
  margin-bottom: 1rem;
}

.plan-price {
  margin-bottom: 1rem;
}

.price-main {
  font-size: 3rem;
  font-weight: 700;
  color: #1f2937;
  line-height: 1;
}

.price-period {
  font-size: 1rem;
  color: #6b7280;
  margin-left: 0.25rem;
}

.billing-note {
  margin-top: 0.5rem;
  font-size: 0.875rem;
}

.original-price {
  text-decoration: line-through;
  color: #9ca3af;
  margin-right: 0.5rem;
}

.savings {
  color: #10b981;
  font-weight: 600;
}

.plan-description {
  color: #6b7280;
  margin: 0;
  line-height: 1.6;
}

.plan-features {
  flex-grow: 1;
  margin-bottom: 2rem;
}

.features-list {
  list-style: none;
  padding: 0;
  margin: 0;
}

.feature-item {
  display: flex;
  align-items: center;
  padding: 0.75rem 0;
  border-bottom: 1px solid #f3f4f6;
}

.feature-item:last-child {
  border-bottom: none;
}

.feature-check {
  color: #10b981;
  margin-right: 0.75rem;
  font-size: 0.875rem;
}

.feature-item-header {
  border-top: 1px solid #e2e8f0;
  margin-top: 0.75rem;
  padding-top: 1rem;
}

.feature-includes {
  font-weight: 600;
  color: #374151;
  font-style: italic;
}

.plan-action {
  text-align: center;
}

.btn-plan {
  width: 100%;
  padding: 1rem 2rem;
  border: none;
  border-radius: 8px;
  font-size: 1rem;
  font-weight: 600;
  transition: all 0.3s ease;
  cursor: pointer;
  margin-bottom: 1rem;
}

.btn-primary {
  background: #667eea;
  color: white;
}

.btn-primary:hover:not(:disabled) {
  background: #5a67d8;
  transform: translateY(-2px);
}

.btn-current {
  background: #10b981;
  color: white;
  cursor: default;
}

.btn-enterprise {
  background: #8b5cf6;
  color: white;
}

.btn-enterprise:hover:not(:disabled) {
  background: #7c3aed;
  transform: translateY(-2px);
}

.btn-plan:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.warning-message {
  background: #fef3c7;
  border: 1px solid #f59e0b;
  color: #92400e;
  padding: 0.75rem;
  border-radius: 8px;
  font-size: 0.875rem;
  text-align: left;
}



/* FAQ Section */
.faq-section {
  background: white;
  padding: 4rem 0;
}

.faq-header h2 {
  font-size: 2.5rem;
  font-weight: 700;
  color: #1f2937;
  margin-bottom: 1rem;
}

.faq-list {
  space-y: 1rem;
}

.faq-item {
  background: #f8fafc;
  border-radius: 8px;
  overflow: hidden;
  margin-bottom: 1rem;
}

.faq-question {
  padding: 1.5rem;
  cursor: pointer;
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-weight: 600;
  color: #374151;
  transition: background-color 0.3s ease;
}

.faq-question:hover {
  background: #e2e8f0;
}

.faq-question i {
  transition: transform 0.3s ease;
}

.faq-question i.rotated {
  transform: rotate(180deg);
}

.faq-answer {
  padding: 0 1.5rem 1.5rem;
  color: #6b7280;
  line-height: 1.6;
}

/* Responsive Design */
@media (max-width: 768px) {
  .hero-title {
    font-size: 2rem;
  }

  .hero-subtitle {
    font-size: 1.125rem;
  }

  .billing-toggle {
    flex-direction: column;
    gap: 1rem;
    padding: 1rem;
  }

  .pricing-card.popular {
    transform: none;
  }

     .pricing-card.popular:hover {
     transform: translateY(-4px);
   }
}

@media (max-width: 576px) {
  .hero-title {
    font-size: 1.75rem;
  }

  .price-main {
    font-size: 2rem;
  }

  .usage-stats {
    grid-template-columns: 1fr;
    gap: 1rem;
  }

  .stat-number {
    font-size: 2rem;
  }
}
</style>
