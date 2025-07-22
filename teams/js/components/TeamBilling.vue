<template>
  <StandardCard
    title="Billing Plan"
    variant="default"
    size="medium"
    shadow="sm"
  >
    <template #header-actions>
      <div class="d-flex align-items-center gap-2">
        <span class="badge" :class="getPlanBadgeClass()">
          {{ getPlanDisplayName() }}
        </span>
        <a
          v-if="canManageBilling"
          :href="`/billing/select-plan/${teamKey}`"
          class="btn btn-sm btn-primary"
        >
          <i class="fas fa-credit-card me-2"></i>
          {{ isFreePlan() ? 'Upgrade Plan' : 'Change Plan' }}
        </a>
      </div>
    </template>

    <div class="billing-content">
      <div class="plan-info">
        <div class="plan-header">
          <h5 class="plan-title">{{ getPlanDisplayName() }}</h5>
          <div class="plan-price">
            <span class="price-amount">{{ getPlanPrice() }}</span>
            <span class="price-period">{{ getPlanPeriod() }}</span>
          </div>
        </div>

        <div v-if="isFreePlan()" class="plan-description">
          <div class="free-plan-message">
            <i class="fas fa-info-circle text-primary me-2"></i>
            <span>You're currently on the Community tier. Upgrade to unlock additional features and higher limits.</span>
          </div>
        </div>

        <div v-if="billingPlanLimits" class="plan-limits">
          <h6 class="limits-title">{{ isFreePlan() ? 'Current Limits' : 'Plan Limits' }}</h6>
          <div class="limits-grid">
            <div class="limit-item">
              <div class="limit-icon">
                <i class="fas fa-box"></i>
              </div>
              <div class="limit-details">
                <span class="limit-label">Products</span>
                <span class="limit-value">{{ formatLimit(billingPlanLimits.max_products) }}</span>
              </div>
            </div>
            <div class="limit-item">
              <div class="limit-icon">
                <i class="fas fa-project-diagram"></i>
              </div>
              <div class="limit-details">
                <span class="limit-label">Projects</span>
                <span class="limit-value">{{ formatLimit(billingPlanLimits.max_projects) }}</span>
              </div>
            </div>
            <div class="limit-item">
              <div class="limit-icon">
                <i class="fas fa-cube"></i>
              </div>
              <div class="limit-details">
                <span class="limit-label">Components</span>
                <span class="limit-value">{{ formatLimit(billingPlanLimits.max_components) }}</span>
              </div>
            </div>
          </div>
        </div>

        <div v-if="!isFreePlan()" class="plan-features">
          <h6 class="features-title">Features</h6>
          <ul class="features-list">
            <li v-for="feature in getPlanFeatures()" :key="feature" class="feature-item">
              <i class="fas fa-check text-success me-2"></i>
              {{ feature }}
            </li>
          </ul>
        </div>

        <div v-if="isFreePlan()" class="upgrade-cta">
          <div class="cta-content">
            <h6 class="cta-title">Ready to upgrade?</h6>
            <p class="cta-description">Unlock advanced features, higher limits, and priority support.</p>
            <a
              v-if="canManageBilling"
              :href="`/billing/select-plan/${teamKey}`"
              class="btn btn-primary"
            >
              <i class="fas fa-arrow-up me-2"></i>
              View Plans
            </a>
          </div>
        </div>
      </div>
    </div>
  </StandardCard>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import StandardCard from '../../../core/js/components/StandardCard.vue'

interface BillingPlanLimits {
  max_products: number
  max_projects: number
  max_components: number
}

const props = defineProps<{
  teamKey: string
  billingPlan: string
  billingPlanLimits: BillingPlanLimits | null
  userRole: string
}>()

const canManageBilling = computed(() => {
  return props.userRole === 'owner'
})

const isFreePlan = (): boolean => {
  return !props.billingPlan || props.billingPlan.toLowerCase() === 'none' || props.billingPlan.toLowerCase() === 'free'
}

const getPlanDisplayName = (): string => {
  if (isFreePlan()) {
    return 'Community'
  }
  return props.billingPlan.charAt(0).toUpperCase() + props.billingPlan.slice(1)
}

const getPlanBadgeClass = (): string => {
  if (isFreePlan()) {
    return 'bg-secondary-subtle text-secondary'
  }
  switch (props.billingPlan.toLowerCase()) {
    case 'business':
      return 'bg-success-subtle text-success'
    case 'enterprise':
      return 'bg-primary-subtle text-primary'
    default:
      return 'bg-success-subtle text-success'
  }
}

const getPlanPrice = (): string => {
  if (isFreePlan()) {
    return '$0'
  }
  switch (props.billingPlan.toLowerCase()) {
    case 'business':
      return '$49'
    case 'enterprise':
      return 'Custom'
    default:
      return 'Contact us'
  }
}

const getPlanPeriod = (): string => {
  if (isFreePlan()) {
    return 'forever'
  }
  switch (props.billingPlan.toLowerCase()) {
    case 'business':
      return 'per month'
    case 'enterprise':
      return 'pricing'
    default:
      return ''
  }
}

const formatLimit = (limit: number): string => {
  if (limit === -1) {
    return 'Unlimited'
  }
  return limit.toString()
}

const getPlanFeatures = (): string[] => {
  switch (props.billingPlan.toLowerCase()) {
    case 'business':
      return [
        'Advanced SBOM analysis',
        'Vulnerability scanning',
        'API access',
        'Priority support',
        'Custom branding'
      ]
    case 'enterprise':
      return [
        'Everything in Business',
        'Unlimited resources',
        'SSO integration',
        'Advanced security',
        'Dedicated support',
        'Custom integrations'
      ]
    default:
      return []
  }
}
</script>

<style scoped>
.billing-content {
  padding: 0;
}

.plan-info {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

.plan-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1.5rem;
  background: linear-gradient(135deg, #f8fafc, #e2e8f0);
  border-radius: 8px;
  margin-bottom: 1rem;
}

.plan-title {
  font-size: 1.25rem;
  font-weight: 600;
  color: #1f2937;
  margin: 0;
}

.plan-price {
  text-align: right;
}

.price-amount {
  font-size: 2rem;
  font-weight: 700;
  color: #059669;
  line-height: 1;
}

.price-period {
  display: block;
  font-size: 0.875rem;
  color: #6b7280;
  margin-top: 0.25rem;
}

.plan-description {
  padding: 1rem 1.5rem;
  background: #f0f9ff;
  border: 1px solid #bae6fd;
  border-radius: 8px;
  margin-bottom: 1rem;
}

.free-plan-message {
  display: flex;
  align-items: flex-start;
  font-size: 0.875rem;
  color: #374151;
  line-height: 1.5;
}

.limits-title,
.features-title {
  font-size: 1rem;
  font-weight: 600;
  color: #374151;
  margin: 0 0 1rem 0;
}

.limits-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 1rem;
}

.limit-item {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 1rem;
  background: #f9fafb;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  transition: all 0.2s ease;
}

.limit-item:hover {
  background: #f3f4f6;
  border-color: #d1d5db;
}

.limit-icon {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  background: linear-gradient(135deg, #4f46e5, #3b82f6);
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  font-size: 1rem;
  flex-shrink: 0;
}

.limit-details {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.limit-label {
  font-size: 0.875rem;
  color: #6b7280;
  font-weight: 500;
}

.limit-value {
  font-size: 1.25rem;
  font-weight: 600;
  color: #1f2937;
}

.features-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.feature-item {
  display: flex;
  align-items: center;
  font-size: 0.875rem;
  color: #374151;
  padding: 0.5rem 0;
}

.upgrade-cta {
  padding: 2rem;
  background: linear-gradient(135deg, #f8fafc, #e2e8f0);
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  text-align: center;
  position: relative;
  overflow: hidden;
}

.upgrade-cta::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 3px;
  background: linear-gradient(90deg, #4f46e5, #3b82f6);
}

.cta-content {
  max-width: 300px;
  margin: 0 auto;
}

.cta-title {
  font-size: 1.125rem;
  font-weight: 600;
  color: #1f2937;
  margin: 0 0 0.5rem 0;
}

.cta-description {
  font-size: 0.875rem;
  color: #6b7280;
  margin: 0 0 1rem 0;
  line-height: 1.5;
}

.badge {
  font-size: 0.75rem;
  font-weight: 500;
  padding: 0.25rem 0.5rem;
}

.bg-success-subtle {
  background-color: #d1fae5;
}

.text-success {
  color: #059669;
}

.bg-secondary-subtle {
  background-color: #f3f4f6;
}

.text-secondary {
  color: #6b7280;
}

.bg-primary-subtle {
  background-color: #eff6ff;
}

.text-primary {
  color: #4f46e5;
}

.btn-sm {
  padding: 0.375rem 0.75rem;
  font-size: 0.875rem;
  line-height: 1.25;
}

.btn-primary {
  background: linear-gradient(135deg, #4f46e5, #3b82f6);
  border: none;
  color: white;
}

.btn-primary:hover {
  background: linear-gradient(135deg, #3730a3, #2563eb);
}

/* Responsive design */
@media (max-width: 768px) {
  .plan-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 1rem;
  }

  .plan-price {
    text-align: left;
  }

  .limits-grid {
    grid-template-columns: 1fr;
  }

  .upgrade-cta {
    padding: 1.5rem;
  }
}
</style>