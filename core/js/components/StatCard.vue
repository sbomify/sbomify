<template>
  <StandardCard
    :title="title"
    variant="stats"
    :size="size"
    :shadow="shadow"
    center-content
  >
    <div class="stat-content">
      <div v-if="loading" class="stat-loading">
        <div class="spinner-border text-muted" role="status">
          <span class="visually-hidden">Loading...</span>
        </div>
      </div>

      <div v-else-if="error" class="stat-error text-danger">
        <i class="fas fa-exclamation-triangle"></i>
        <span class="ms-2">{{ error }}</span>
      </div>

      <div v-else class="stat-display">
        <div class="stat-value">
          <span class="display-4" :class="valueClasses">{{ formattedValue }}</span>
          <span v-if="unit" class="stat-unit">{{ unit }}</span>
        </div>

        <div v-if="subtitle" class="stat-subtitle text-muted">
          {{ subtitle }}
        </div>

        <div v-if="trend !== undefined" class="stat-trend mt-2">
          <i
            class="fas me-1"
            :class="{
              'fa-arrow-up text-success': trend > 0,
              'fa-arrow-down text-danger': trend < 0,
              'fa-minus text-muted': trend === 0
            }"
          ></i>
          <span
            class="trend-value"
            :class="{
              'text-success': trend > 0,
              'text-danger': trend < 0,
              'text-muted': trend === 0
            }"
          >
            {{ Math.abs(trend) }}%
          </span>
          <span class="text-muted ms-1">{{ trendPeriod }}</span>
        </div>
      </div>
    </div>

    <template v-if="hasActions" #actions>
      <slot name="actions"></slot>
    </template>
  </StandardCard>
</template>

<script setup lang="ts">
import { computed, useSlots } from 'vue'
import StandardCard from './StandardCard.vue'

interface Props {
  title: string
  value?: number | string | null
  unit?: string
  subtitle?: string
  trend?: number
  trendPeriod?: string
  loading?: boolean
  error?: string | null
  size?: 'small' | 'medium' | 'large'
  shadow?: 'none' | 'sm' | 'md' | 'lg'
  colorScheme?: 'default' | 'primary' | 'success' | 'warning' | 'danger' | 'muted' | 'slate'
  formatAsNumber?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  value: 0,
  unit: '',
  subtitle: '',
  trendPeriod: 'vs last month',
  loading: false,
  error: null,
  size: 'medium',
  shadow: 'sm',
  colorScheme: 'default',
  formatAsNumber: true
})

const slots = useSlots()

const hasActions = computed(() => !!slots.actions)

const formattedValue = computed(() => {
  if (props.value === null || props.value === undefined) {
    return '—'
  }

  if (typeof props.value === 'string') {
    return props.value
  }

  if (props.formatAsNumber && typeof props.value === 'number') {
    // Format large numbers with commas
    return props.value.toLocaleString()
  }

  return String(props.value)
})

const valueClasses = computed(() => {
  const classes = ['stat-number']

  switch (props.colorScheme) {
    case 'primary':
      classes.push('text-primary-subtle')
      break
    case 'success':
      classes.push('text-success-subtle')
      break
    case 'warning':
      classes.push('text-warning-subtle')
      break
    case 'danger':
      classes.push('text-danger-subtle')
      break
    case 'muted':
      classes.push('text-muted-emphasis')
      break
    case 'slate':
      classes.push('text-slate')
      break
    default:
      classes.push('text-dark-emphasis')
  }

  return classes.join(' ')
})
</script>

<style scoped>
.stat-content {
  padding: 0.5rem 0;
}

.stat-loading {
  padding: 2rem 0;
}

.stat-error {
  padding: 1rem 0;
  font-size: 0.9rem;
}

.stat-display {
  min-height: 80px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
}

.stat-value {
  display: flex;
  align-items: baseline;
  justify-content: center;
  gap: 0.25rem;
  margin-bottom: 0.5rem;
}

.stat-number {
  font-weight: 700;
  line-height: 1;
}

.stat-unit {
  font-size: 1rem;
  font-weight: 500;
  color: #6c757d;
  margin-left: 0.25rem;
}

.stat-subtitle {
  font-size: 0.875rem;
  text-align: center;
  margin-bottom: 0.5rem;
}

.stat-trend {
  font-size: 0.875rem;
  display: flex;
  align-items: center;
  justify-content: center;
}

.trend-value {
  font-weight: 600;
}

/* Professional color classes */
.text-primary-subtle {
  color: #4a90e2 !important;
}

.text-success-subtle {
  color: #5cb85c !important;
}

.text-warning-subtle {
  color: #f0ad4e !important;
}

.text-danger-subtle {
  color: #d9534f !important;
}

.text-muted-emphasis {
  color: #6c757d !important;
}

.text-slate {
  color: #64748b !important;
}

.text-dark-emphasis {
  color: #2c3e50 !important;
}

/* Responsive font sizes */
@media (max-width: 768px) {
  .stat-number {
    font-size: 2rem !important;
  }

  .stat-unit {
    font-size: 0.875rem;
  }
}

@media (max-width: 576px) {
  .stat-number {
    font-size: 1.75rem !important;
  }

  .stat-subtitle {
    font-size: 0.8rem;
  }

  .stat-trend {
    font-size: 0.8rem;
  }
}
</style>