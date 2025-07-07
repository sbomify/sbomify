<template>
  <div class="public-card-wrapper" :class="wrapperClasses">
    <StandardCard
      :title="title"
      :variant="mappedVariant"
      :size="mappedSize"
      :shadow="hoverable ? 'md' : 'sm'"
      :noPadding="!padded"
      :infoIcon="icon"
    >
      <!-- Map header slot -->
      <template v-if="$slots.header" #header-actions>
        <slot name="header"></slot>
      </template>

      <!-- Map info notice if we have subtitle -->
      <template v-if="subtitle" #info-notice>
        {{ subtitle }}
      </template>

      <!-- Main content slot -->
      <slot></slot>

      <!-- Map footer slot -->
      <template v-if="$slots.footer" #footer>
        <slot name="footer"></slot>
      </template>
    </StandardCard>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import StandardCard from './StandardCard.vue'

interface Props {
  title?: string
  subtitle?: string
  icon?: string
  variant?: 'default' | 'primary' | 'secondary' | 'success' | 'warning' | 'error' | 'info'
  size?: 'sm' | 'md' | 'lg'
  hoverable?: boolean
  padded?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  title: '',
  subtitle: '',
  icon: 'fas fa-info-circle',
  variant: 'default',
  size: 'md',
  hoverable: false,
  padded: true
})

// Map PublicCard variants to StandardCard variants
const mappedVariant = computed((): 'default' | 'stats' | 'plan' | 'modal' | 'settings' | 'dangerzone' => {
  switch (props.variant) {
    case 'primary':
    case 'secondary':
    case 'success':
    case 'warning':
    case 'error':
    case 'info':
      return 'default' // StandardCard doesn't have these color variants, use default
    case 'default':
    default:
      return 'default'
  }
})

// Map PublicCard sizes to StandardCard sizes
const mappedSize = computed((): 'small' | 'medium' | 'large' => {
  switch (props.size) {
    case 'sm':
      return 'small'
    case 'md':
      return 'medium'
    case 'lg':
      return 'large'
    default:
      return 'medium'
  }
})

// Generate wrapper classes for variant styling
const wrapperClasses = computed(() => {
  return [
    `public-card--${props.variant}`,
    { 'public-card--hoverable': props.hoverable }
  ]
})
</script>

<style scoped>
/*
 * Custom styling for PublicCard variants that StandardCard doesn't handle
 * These styles will be applied on top of StandardCard's base styles
 */

.public-card-wrapper :deep(.standard-card .card) {
  transition: all 0.2s ease;
}

/* Hoverable effect */
.public-card--hoverable :deep(.standard-card .card):hover {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08), 0 2px 8px rgba(0, 0, 0, 0.04);
}

/* Primary variant styling */
.public-card--primary :deep(.standard-card .card) {
  border-color: var(--brand-color, #4f46e5);
  box-shadow: 0 1px 3px rgba(79, 70, 229, 0.12), 0 1px 2px rgba(79, 70, 229, 0.08);
}

.public-card--primary :deep(.standard-card .card-header) {
  background: var(--brand-color, #4f46e5);
  color: white;
  border-bottom-color: rgba(255, 255, 255, 0.15);
}

.public-card--primary :deep(.standard-card .card-title) {
  color: white !important;
}

/* Secondary variant styling */
.public-card--secondary :deep(.standard-card .card) {
  border-color: var(--accent-color, #7c8b9d);
}

.public-card--secondary :deep(.standard-card .card-header) {
  background: linear-gradient(135deg, var(--accent-color, #7c8b9d) 0%, var(--accent-color-dark, #6b7a8a) 100%);
  color: white;
}

.public-card--secondary :deep(.standard-card .card-title) {
  color: white !important;
}

/* Success variant styling */
.public-card--success :deep(.standard-card .card) {
  border-color: #10b981;
}

.public-card--success :deep(.standard-card .card-header) {
  background: linear-gradient(135deg, #10b981 0%, #059669 100%);
  color: white;
}

.public-card--success :deep(.standard-card .card-title) {
  color: white !important;
}

/* Warning variant styling */
.public-card--warning :deep(.standard-card .card) {
  border-color: #f59e0b;
}

.public-card--warning :deep(.standard-card .card-header) {
  background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%);
  color: white;
}

.public-card--warning :deep(.standard-card .card-title) {
  color: white !important;
}

/* Error variant styling */
.public-card--error :deep(.standard-card .card) {
  border-color: #ef4444;
}

.public-card--error :deep(.standard-card .card-header) {
  background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%);
  color: white;
}

.public-card--error :deep(.standard-card .card-title) {
  color: white !important;
}

/* Info variant styling */
.public-card--info :deep(.standard-card .card) {
  border-color: #3b82f6;
}

.public-card--info :deep(.standard-card .card-header) {
  background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);
  color: white;
}

.public-card--info :deep(.standard-card .card-title) {
  color: white !important;
}
</style>