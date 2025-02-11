<template>
  <div class="container py-5">
    <h1 class="text-center mb-5">Choose Your Plan</h1>

    <div class="row mb-4">
      <div class="col-12">
        <div class="card">
          <div class="card-header">
            <h5 class="card-title mb-0">Current Usage</h5>
          </div>
          <div class="card-body">
            <p class="mb-0">
              Products: {{ usage.products }},
              Projects: {{ usage.projects }},
              Components: {{ usage.components }}
            </p>
          </div>
        </div>
      </div>
    </div>

    <div class="row row-cols-1 row-cols-md-3 mb-3 text-center">
      <template v-for="planKey in ['community', 'business', 'enterprise']" :key="planKey">
        <div class="col">
          <div
            v-if="getPlan(planKey)"
            class="card mb-4 rounded-3 shadow-sm"
            :class="{ 'border-emphasis': isCurrentPlan(getPlan(planKey)!) }"
          >
            <div
              class="card-header py-3"
              :class="{ 'bg-emphasis text-emphasis border-emphasis': isCurrentPlan(getPlan(planKey)!) }"
            >
              <h4 class="my-0 fw-normal card-title">{{ getPlan(planKey)!.name }}</h4>
            </div>
            <div class="card-body">
              <h1 class="card-title pricing-card-title">
                <template v-if="planKey === 'community'">Free</template>
                <template v-else-if="planKey === 'business'">
                  $199<small class="text-body-secondary fw-light">/mo</small>
                </template>
                <template v-else>Contact Us</template>
              </h1>
              <p class="mt-3 mb-4">{{ getPlan(planKey)!.description }}</p>

              <ul class="list-unstyled mt-3 mb-4">
                <li>{{ getPlan(planKey)!.max_products ? getPlan(planKey)!.max_products : 'Unlimited' }} Products</li>
                <li>{{ getPlan(planKey)!.max_projects ? getPlan(planKey)!.max_projects : 'Unlimited' }} Projects</li>
                <li>{{ getPlan(planKey)!.max_components ? getPlan(planKey)!.max_components : 'Unlimited' }} Components</li>
              </ul>

              <div v-if="!canDowngrade(getPlan(planKey)!).can" class="alert alert-warning mb-3" role="alert">
                {{ canDowngrade(getPlan(planKey)!).message }}
              </div>

              <div class="d-grid gap-2">
                <div v-if="planKey === 'business'" class="btn-group mb-3" role="group" aria-label="Billing period">
                  <input type="radio" class="btn-check" name="billing_period" value="monthly" id="monthly" v-model="billingPeriod">
                  <label class="btn btn-outline-secondary" for="monthly">Monthly ($199/mo)</label>

                  <input type="radio" class="btn-check" name="billing_period" value="annual" id="annual" v-model="billingPeriod">
                  <label class="btn btn-outline-secondary" for="annual">Annual ($159/mo)</label>
                </div>
                <div v-else class="billing-period-spacer mb-3"></div>

                <button
                  type="button"
                  class="w-100 btn"
                  :class="{
                    'btn-secondary': !isCurrentPlan(getPlan(planKey)!),
                    'btn-outline-secondary': isCurrentPlan(getPlan(planKey)!)
                  }"
                  :disabled="isCurrentPlan(getPlan(planKey)!)"
                  @click="handlePlanSelection(getPlan(planKey)!)"
                >
                  {{ getButtonText(getPlan(planKey)!) }}
                </button>
              </div>
            </div>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue';
import $axios from '../../../core/js/utils';

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

const props = defineProps<{
  initialTeamKey?: string;
}>();

const emit = defineEmits(['plan-selected']);

const plans = ref<Plan[]>([]);
const usage = ref<Usage>({ products: 0, projects: 0, components: 0, current_plan: null });
const currentPlan = ref<string | null>(null);
const billingPeriod = ref('monthly');

function canDowngrade(plan: Plan) {
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
}

async function handlePlanSelection(plan: Plan) {
  try {
    if (plan.key === 'enterprise') {
      // Redirect to enterprise contact page
      window.location.href = '/billing/enterprise-contact/';
      return;
    }

    // If downgrading to community, show warning about public SBOMs
    if (plan.key === 'community' && currentPlan.value !== 'business') {
      const { default: Swal } = await import('sweetalert2');
      const result = await Swal.fire({
        title: 'Confirm Downgrade',
        html:
          'Are you sure you want to downgrade to the Community plan?<br><br>' +
          '<strong class="text-warning">Warning:</strong> All your SBOMs will become public.<br><br>' +
          'This will also immediately cancel your subscription.',
        icon: 'warning',
        showCancelButton: true,
        confirmButtonText: 'Yes, downgrade',
        cancelButtonText: 'Cancel',
        customClass: {
          confirmButton: 'btn btn-secondary swal-confirm-button',
          cancelButton: 'btn btn-outline-secondary swal-cancel-button',
          popup: 'swal-modal'
        },
        buttonsStyling: false
      });
      if (!result.isConfirmed) return;
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
      const { default: Swal } = await import('sweetalert2');
      await Swal.fire({
        title: 'Success',
        text: 'Plan updated successfully',
        icon: 'success',
        toast: true,
        position: 'top-end',
        showConfirmButton: false,
        timer: 3000
      });
      emit('plan-selected');
    }
  } catch (error: any) {
    const { default: Swal } = await import('sweetalert2');
    await Swal.fire({
      title: 'Error',
      text: error.response?.data?.detail || 'Failed to change plan',
      icon: 'error',
      toast: true,
      position: 'top-end',
      showConfirmButton: false,
      timer: 3000
    });
  }
}

function getButtonText(plan: Plan) {
  if (plan.key === currentPlan.value) {
    return 'Current Plan';
  } else if (!currentPlan.value && plan.key === 'community') {
    return 'Select Plan';
  } else if (plan.key === 'enterprise') {
    return 'Contact Sales';
  } else {
    return currentPlan.value ? 'Change Plan' : 'Select Plan';
  }
}

function isCurrentPlan(plan: Plan) {
  return plan.key === currentPlan.value;
}

function getPlan(key: string): Plan | undefined {
  return plans.value.find(p => p.key === key);
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
.card {
  border: 1px solid #dee2e6;
  border-radius: 0.5rem;
  margin-bottom: 1rem;
}

.card-header {
  background: #f8f9fa;
  border-bottom: 1px solid #eaecef;
  padding: 1.25rem;
  border-radius: 8px 8px 0 0;
}

.card-body {
  padding: 1.25rem;
}

/* Specific styles for plan cards */
.row-cols-md-3 .card-body {
  display: flex;
  flex-direction: column;
  min-height: 400px;
}

.card-title {
  color: #2c3e50;
  font-size: 1.1rem;
  font-weight: 600;
  margin: 0;
}

.btn {
  padding: 0.75rem 1.5rem;
  font-weight: 500;
  border-radius: 6px;
  transition: all 0.2s ease;
}

.btn-secondary {
  background: #6c757d;
  border: none;
  color: #fff;
}

.btn-secondary:hover {
  background: #5c636a;
  transform: translateY(-1px);
  color: #fff;
}

.btn-outline-secondary {
  color: #6c757d;
  border-color: #6c757d;
}

.btn-outline-secondary:hover {
  background: #6c757d;
  color: #fff;
  transform: translateY(-1px);
}

.border-emphasis {
  border-color: #6c757d !important;
}

.bg-emphasis {
  background-color: #6c757d !important;
}

.text-emphasis {
  color: #fff !important;
}

/* Add styles for the billing period buttons */
.btn-group .btn-outline-secondary {
  background-color: transparent;
  color: #6c757d;
}

.btn-group .btn-outline-secondary:hover,
.btn-group .btn-check:checked + .btn-outline-secondary {
  background-color: #6c757d;
  color: #fff;
}

/* Add styles for the card headers */
.card-header.bg-emphasis .card-title {
  color: #fff;
}

.pricing-card-title {
  color: #2c3e50;
  font-size: 2.5rem;
  font-weight: 600;
}

/* Add exact height for the billing period spacer to match the btn-group */
.billing-period-spacer {
  height: 58px;
  margin-top: 10px;
}

/* Push buttons to bottom of card */
.d-grid {
  margin-top: auto;
}

/* Add consistent spacing for plan features */
.list-unstyled {
  margin: 1.5rem 0;
  flex-grow: 1;
}

/* SweetAlert2 custom styling */
:global(.swal-modal) {
  font-family: inherit;
}

:global(.swal-confirm-button),
:global(.swal-cancel-button) {
  padding: 0.75rem 1.5rem;
  font-weight: 500;
  border-radius: 6px;
  transition: all 0.2s ease;
  margin: 0 0.5rem;
}

:global(.swal-actions) {
  margin-top: 1.5rem;
  gap: 1rem;
}

:global(.swal-confirm-button) {
  background: #6c757d;
  border: none;
  color: #fff;
}

:global(.swal-confirm-button:hover) {
  background: #5c636a;
  transform: translateY(-1px);
}

:global(.swal-cancel-button) {
  color: #6c757d;
  border: 1px solid #6c757d;
  background: transparent;
}

:global(.swal-cancel-button:hover) {
  background: #6c757d;
  color: #fff;
  transform: translateY(-1px);
}
</style>