<template>
  <div class="container py-5">
    <h1 class="text-center mb-5">Choose Your Plan</h1>

    <div class="row mb-4">
      <div class="col-12">
        <StandardCard title="Current Usage" variant="stats">
          <p class="mb-0">
            Products: {{ usage.products }},
            Projects: {{ usage.projects }},
            Components: {{ usage.components }}
          </p>
        </StandardCard>
      </div>
    </div>

    <div class="row row-cols-1 row-cols-md-3 mb-3 text-center">
      <template v-for="planKey in ['community', 'business', 'enterprise']" :key="planKey">
        <div class="col">
          <PlanCard
            v-if="getPlan(planKey)"
            :plan-name="getPlan(planKey)!.name"
            :price="getPlanPrice(planKey)"
            :price-period="getPlanPricePeriod(planKey)"
            :description="getPlan(planKey)!.description"
            :features="getPlanFeatures(planKey)"
            :is-current-plan="isCurrentPlan(getPlan(planKey)!)"
            :button-text="getButtonText(getPlan(planKey)!)"
            :button-disabled="!canSelectPlan(getPlan(planKey)!)"
            :warning-message="canDowngrade(getPlan(planKey)!).can ? '' : canDowngrade(getPlan(planKey)!).message"
            @action="handlePlanSelection(getPlan(planKey)!)"
          >
            <template v-if="planKey === 'business'" #form-controls>
              <div class="btn-group mb-3" role="group" aria-label="Billing period">
                <input id="monthly" v-model="billingPeriod" type="radio" class="btn-check" name="billing_period" value="monthly">
                <label class="btn btn-outline-secondary" for="monthly">Monthly ($199/mo)</label>

                <input id="annual" v-model="billingPeriod" type="radio" class="btn-check" name="billing_period" value="annual">
                <label class="btn btn-outline-secondary" for="annual">Annual ($159/mo)</label>
              </div>
            </template>

            <template v-if="planKey === 'business'" #pricing>
              <template v-if="billingPeriod === 'monthly'">
                $199<small class="text-body-secondary fw-light">/mo</small>
              </template>
              <template v-else>
                $159<small class="text-body-secondary fw-light">/mo</small>
                <div class="text-success small">Save 20% annually</div>
              </template>
            </template>
          </PlanCard>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue';
import $axios from '../../../core/js/utils';
import { showSuccess, showError, showConfirmation } from '../../../core/js/alerts';
import { AxiosError } from 'axios';
import StandardCard from '../../../core/js/components/StandardCard.vue';
import PlanCard from '../../../core/js/components/PlanCard.vue';

interface Plan {
  key: string;
  name: string;
  description: string;
  max_products: number | null;
  max_projects: number | null;
  max_components: number | null;
}

interface Usage {
  products: number;
  projects: number;
  components: number;
  current_plan: string | null;
}

interface PlanFeature {
  key: string;
  label: string;
}

const props = defineProps<{
  initialTeamKey?: string;
}>();

const emit = defineEmits(['plan-selected']);

const plans = ref<Plan[]>([]);
const usage = ref<Usage>({ products: 0, projects: 0, components: 0, current_plan: null });
const currentPlan = ref<string | null>(null);
const billingPeriod = ref('monthly');

const getPlan = (key: string): Plan | undefined => {
  return plans.value.find(p => p.key === key);
};

const getPlanPrice = (planKey: string): number => {
  switch (planKey) {
    case 'community':
      return 0;
    case 'business':
      return billingPeriod.value === 'monthly' ? 199 : 159;
    case 'enterprise':
      return -1; // Contact us pricing
    default:
      return 0;
  }
};

const getPlanPricePeriod = (planKey: string): string => {
  if (planKey === 'enterprise') return '';
  return '/mo';
};

const getPlanFeatures = (planKey: string): PlanFeature[] => {
  const plan = getPlan(planKey);
  if (!plan) return [];

  return [
    {
      key: 'products',
      label: `${plan.max_products ? plan.max_products : 'Unlimited'} Products`
    },
    {
      key: 'projects',
      label: `${plan.max_projects ? plan.max_projects : 'Unlimited'} Projects`
    },
    {
      key: 'components',
      label: `${plan.max_components ? plan.max_components : 'Unlimited'} Components`
    }
  ];
};

const canDowngrade = (plan: Plan) => {
  // If it's the current plan, always allow
  if (plan.key === currentPlan.value) {
    return { can: true, message: '' };
  }

  // If upgrading to a higher tier plan, always allow
  const currentPlanData = plans.value.find(p => p.key === currentPlan.value);
  if (!currentPlanData || (currentPlanData.max_products && !plan.max_products)) {
    return { can: true, message: '' };
  }

  // Check usage limits
  if (!plan.max_products && !plan.max_projects && !plan.max_components) {
    return { can: true, message: '' };
  }

  if (plan.max_products && usage.value.products > plan.max_products) {
    return { can: false, message: `Cannot downgrade: You have ${usage.value.products} products, but this plan only allows ${plan.max_products}` };
  }

  if (plan.max_projects && usage.value.projects > plan.max_projects) {
    return { can: false, message: `Cannot downgrade: You have ${usage.value.projects} projects, but this plan only allows ${plan.max_projects}` };
  }

  if (plan.max_components && usage.value.components > plan.max_components) {
    return { can: false, message: `Cannot downgrade: You have ${usage.value.components} components, but this plan only allows ${plan.max_components}` };
  }

  return { can: true, message: '' };
};

const canSelectPlan = (plan: Plan): boolean => {
  return canDowngrade(plan).can;
};

const isCurrentPlan = (plan: Plan): boolean => {
  return plan.key === currentPlan.value;
};

const getButtonText = (plan: Plan): string => {
  if (plan.key === currentPlan.value) {
    return 'Current Plan';
  } else if (!currentPlan.value && plan.key === 'community') {
    return 'Select Plan';
  } else if (plan.key === 'enterprise') {
    return 'Contact Sales';
  } else {
    return currentPlan.value ? 'Change Plan' : 'Select Plan';
  }
};

async function handlePlanSelection(plan: Plan) {
  try {
    if (plan.key === 'enterprise') {
      // Redirect to enterprise contact page
      window.location.href = '/billing/enterprise-contact/';
      return;
    }

    // If downgrading to community from a paid plan, show warning about public SBOMs
    if (plan.key === 'community' && currentPlan.value && currentPlan.value !== 'community') {
      const confirmed = await showConfirmation({
        title: 'Confirm Downgrade',
        message: 'Are you sure you want to downgrade to the Community plan? All your SBOMs will become public. This will also immediately cancel your subscription.',
        confirmButtonText: 'Yes, downgrade',
        cancelButtonText: 'Cancel',
        type: 'warning'
      });

      if (!confirmed) return;
    }

    const response = await $axios.post(`/api/v1/billing/change-plan/`, {
      plan: plan.key,
      billing_period: plan.key === 'business' ? billingPeriod.value : null,
      team_key: props.initialTeamKey
    });

    if (response.data.redirect_url) {
      // For business plan, redirect to Stripe checkout
      window.location.href = response.data.redirect_url;
    } else {
      // For community plan, show success message and emit event
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
/* Enhanced button styles for billing period selection */
.btn-group .btn-outline-secondary {
  background-color: transparent;
  color: #6c757d;
}

.btn-group .btn-outline-secondary:hover,
.btn-group .btn-check:checked + .btn-outline-secondary {
  background-color: #6c757d;
  color: #fff;
}

/* Responsive adjustments */
@media (max-width: 768px) {
  .btn-group {
    flex-direction: column;
    width: 100%;
  }

  .btn-group .btn {
    border-radius: 0.375rem !important;
    margin-bottom: 0.5rem;
  }

  .btn-group .btn:last-child {
    margin-bottom: 0;
  }
}
</style>