<template>
  <StandardCard
    :title="planName"
    variant="plan"
    :emphasis="isCurrentPlan"
    :shadow="isCurrentPlan ? 'md' : 'sm'"
    size="medium"
  >
    <div class="plan-content">
      <!-- Pricing -->
      <div class="plan-pricing">
        <h1 class="pricing-title">
          <slot name="pricing">
            <template v-if="price === 0">Community</template>
            <template v-else-if="price > 0">
              ${{ price }}<small class="pricing-period">{{ pricePeriod }}</small>
            </template>
            <template v-else>Contact Us</template>
          </slot>
        </h1>
      </div>

      <!-- Description -->
      <div v-if="description" class="plan-description">
        <p class="text-muted">{{ description }}</p>
      </div>

      <!-- Features -->
      <div v-if="features.length > 0" class="plan-features">
        <ul class="list-unstyled">
          <li v-for="feature in features" :key="feature.key" class="feature-item">
            <i class="fas fa-check text-success me-2"></i>
            {{ feature.label }}
          </li>
        </ul>
      </div>

      <!-- Custom Content Slot -->
      <div v-if="hasCustomContent" class="plan-custom-content">
        <slot></slot>
      </div>

      <!-- Warning/Info Messages -->
      <div v-if="warningMessage" class="alert alert-warning mb-3" role="alert">
        <i class="fas fa-exclamation-triangle me-2"></i>
        {{ warningMessage }}
      </div>

      <div v-if="infoMessage" class="alert alert-info mb-3" role="alert">
        <i class="fas fa-info-circle me-2"></i>
        {{ infoMessage }}
      </div>

      <!-- Actions Section -->
      <div class="plan-actions">
        <!-- Custom Form Controls (like billing period selection) -->
        <div v-if="hasFormControls" class="plan-form-controls mb-3">
          <slot name="form-controls"></slot>
        </div>

        <!-- Action Button -->
        <div class="d-grid gap-2">
          <button
            type="button"
            class="btn w-100"
            :class="buttonClasses"
            :disabled="buttonDisabled"
            @click="handleAction"
          >
            <i v-if="buttonIcon" :class="buttonIcon" class="me-2"></i>
            {{ buttonText }}
          </button>
        </div>
      </div>
    </div>

    <template v-if="hasFooterActions" #footer>
      <slot name="footer-actions"></slot>
    </template>
  </StandardCard>
</template>

<script setup lang="ts">
import { computed, useSlots } from 'vue'
import StandardCard from './StandardCard.vue'

interface Feature {
  key: string
  label: string
  included?: boolean
}

interface Props {
  planName: string
  price?: number
  pricePeriod?: string
  description?: string
  features?: Feature[]
  isCurrentPlan?: boolean
  buttonText?: string
  buttonIcon?: string
  buttonVariant?: 'primary' | 'secondary' | 'outline-primary' | 'outline-secondary' | 'success' | 'danger'
  buttonDisabled?: boolean
  warningMessage?: string
  infoMessage?: string
  loading?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  price: 0,
  pricePeriod: '/mo',
  description: '',
  features: () => [],
  isCurrentPlan: false,
  buttonText: 'Select Plan',
  buttonIcon: '',
  buttonVariant: 'primary',
  buttonDisabled: false,
  warningMessage: '',
  infoMessage: '',
  loading: false
})

const emit = defineEmits<{
  action: []
}>()

const slots = useSlots()

const hasCustomContent = computed(() => !!slots.default)
const hasFormControls = computed(() => !!slots['form-controls'])
const hasFooterActions = computed(() => !!slots['footer-actions'])

const buttonClasses = computed(() => {
  const classes = []

  if (props.isCurrentPlan) {
    classes.push('btn-outline-secondary')
  } else {
    switch (props.buttonVariant) {
      case 'primary':
        classes.push('btn-primary')
        break
      case 'secondary':
        classes.push('btn-secondary')
        break
      case 'outline-primary':
        classes.push('btn-outline-primary')
        break
      case 'outline-secondary':
        classes.push('btn-outline-secondary')
        break
      case 'success':
        classes.push('btn-success')
        break
      case 'danger':
        classes.push('btn-danger')
        break
      default:
        classes.push('btn-primary')
    }
  }

  if (props.loading) {
    classes.push('btn-loading')
  }

  return classes.join(' ')
})

const buttonDisabled = computed(() => {
  return props.buttonDisabled || props.loading || props.isCurrentPlan
})

const handleAction = () => {
  if (!buttonDisabled.value) {
    emit('action')
  }
}
</script>

<style scoped>
.plan-content {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 350px;
}

.plan-pricing {
  text-align: center;
  margin-bottom: 1rem;
}

.pricing-title {
  color: #2c3e50;
  font-size: 2.5rem;
  font-weight: 600;
  margin: 0;
  line-height: 1.2;
}

.pricing-period {
  font-size: 1rem;
  font-weight: 400;
  color: #6c757d;
  margin-left: 0.25rem;
}

.plan-description {
  text-align: center;
  margin-bottom: 1.5rem;
}

.plan-description p {
  margin: 0;
  font-size: 0.95rem;
  line-height: 1.5;
}

.plan-features {
  flex-grow: 1;
  margin-bottom: 1.5rem;
}

.feature-item {
  padding: 0.4rem 0;
  font-size: 0.9rem;
  line-height: 1.4;
  display: flex;
  align-items: flex-start;
}

.feature-item i {
  margin-top: 0.15rem;
  flex-shrink: 0;
}

.plan-custom-content {
  margin-bottom: 1.5rem;
}

.plan-actions {
  margin-top: auto;
}

.plan-form-controls {
  text-align: center;
}

.btn {
  padding: 0.75rem 1.5rem;
  font-weight: 500;
  border-radius: 6px;
  transition: all 0.2s ease;
  position: relative;
}

.btn:not(:disabled):hover {
  transform: translateY(-1px);
}

.btn-loading {
  color: transparent !important;
}

.btn-loading::after {
  content: '';
  position: absolute;
  width: 1rem;
  height: 1rem;
  top: 50%;
  left: 50%;
  margin-left: -0.5rem;
  margin-top: -0.5rem;
  border: 2px solid transparent;
  border-top-color: #ffffff;
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  0% { transform: rotate(0deg); }
  100% { transform: rotate(360deg); }
}

/* Enhanced button styles for plan cards */
.btn-primary {
  background: #007bff;
  border-color: #007bff;
  color: #fff;
}

.btn-primary:hover {
  background: #0056b3;
  border-color: #0056b3;
}

.btn-secondary {
  background: #6c757d;
  border-color: #6c757d;
  color: #fff;
}

.btn-secondary:hover {
  background: #5c636a;
  border-color: #5c636a;
}

.btn-outline-secondary {
  color: #6c757d;
  border-color: #6c757d;
  background: transparent;
}

.btn-outline-secondary:hover {
  background: #6c757d;
  color: #fff;
}

/* Alert styling within plan cards */
.alert {
  font-size: 0.875rem;
  padding: 0.75rem;
  border-radius: 0.375rem;
}

.alert i {
  font-size: 1rem;
}

/* Responsive adjustments */
@media (max-width: 768px) {
  .plan-content {
    min-height: 300px;
  }

  .pricing-title {
    font-size: 2rem;
  }

  .feature-item {
    font-size: 0.85rem;
  }
}

@media (max-width: 576px) {
  .pricing-title {
    font-size: 1.75rem;
  }

  .btn {
    padding: 0.65rem 1.25rem;
    font-size: 0.9rem;
  }
}
</style>