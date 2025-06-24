<template>
  <div class="standard-card" :class="containerClasses">
    <div class="card" :class="cardClasses">
      <div
        v-if="title || hasHeaderActions"
        class="card-header"
        :class="headerClasses"
      >
        <div class="header-content">
          <h4
            v-if="title"
            class="card-title mb-0"
            :style="collapsible ? 'cursor: pointer;' : ''"
            @click="collapsible ? toggleCollapse() : null"
          >
            {{ title }}
            <i v-if="collapsible" class="fas ms-2" :class="isExpanded ? 'fa-chevron-down' : 'fa-chevron-right'"></i>
          </h4>
          <div v-if="hasHeaderActions" class="header-actions">
            <slot name="header-actions"></slot>
          </div>
        </div>
      </div>

      <div :id="collapseId" class="card-body" :class="bodyClasses">
        <!-- Info Notice Slot -->
        <div v-if="hasInfoNotice" class="augmentation-notice d-flex align-items-center mb-3">
          <i :class="infoIcon" class="me-2" style="color: #4f46e5;"></i>
          <span class="text-muted">
            <slot name="info-notice"></slot>
          </span>
        </div>

        <!-- Main Content Slot -->
        <slot></slot>

        <!-- Actions Slot -->
        <div v-if="hasActions" class="card-actions">
          <slot name="actions"></slot>
        </div>
      </div>

      <!-- Footer Actions Slot -->
      <div v-if="hasFooter" class="card-footer" :class="footerClasses">
        <slot name="footer"></slot>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, useSlots } from 'vue'

interface Props {
  title?: string
  collapsible?: boolean
  defaultExpanded?: boolean
  infoIcon?: string
  storageKey?: string
  variant?: 'default' | 'stats' | 'plan' | 'modal' | 'settings'
  size?: 'small' | 'medium' | 'large'
  emphasis?: boolean
  centerContent?: boolean
  noPadding?: boolean
  shadow?: 'none' | 'sm' | 'md' | 'lg'
}

const props = withDefaults(defineProps<Props>(), {
  title: '',
  collapsible: false,
  defaultExpanded: true,
  infoIcon: 'fas fa-info-circle',
  storageKey: '',
  variant: 'default',
  size: 'medium',
  emphasis: false,
  centerContent: false,
  noPadding: false,
  shadow: 'sm'
})

const slots = useSlots()
const collapseId = `collapse-${Math.random().toString(36).substr(2, 9)}`

// Initialize collapse state from session storage if available
const getInitialExpandedState = (): boolean => {
  if (props.storageKey) {
    const stored = sessionStorage.getItem(`card-collapse-${props.storageKey}`)
    if (stored !== null) {
      return stored === 'true'
    }
  }
  return props.defaultExpanded
}

const isExpanded = ref(getInitialExpandedState())

const hasInfoNotice = computed(() => !!slots['info-notice'])
const hasActions = computed(() => !!slots.actions)
const hasFooter = computed(() => !!slots.footer)
const hasHeaderActions = computed(() => !!slots['header-actions'])

const containerClasses = computed(() => {
  const classes = []

  if (props.size === 'small') classes.push('mt-2')
  else if (props.size === 'large') classes.push('mt-4')
  else classes.push('mt-3')

  return classes.join(' ')
})

const cardClasses = computed(() => {
  const classes = []

  // Variant-specific classes
  switch (props.variant) {
    case 'stats':
      classes.push('stats-card')
      break
    case 'plan':
      classes.push('plan-card')
      if (props.emphasis) classes.push('plan-emphasis')
      break
    case 'modal':
      classes.push('modal-card')
      break
    case 'settings':
      classes.push('settings-card')
      break
  }

  // Shadow classes
  switch (props.shadow) {
    case 'none':
      classes.push('shadow-none')
      break
    case 'md':
      classes.push('shadow-md')
      break
    case 'lg':
      classes.push('shadow-lg')
      break
    default:
      classes.push('shadow-sm')
  }

  return classes.join(' ')
})

const headerClasses = computed(() => {
  const classes = []

  if (props.collapsible) classes.push('collapsible-header')
  if (props.emphasis && props.variant === 'plan') {
    classes.push('bg-emphasis', 'text-emphasis', 'border-emphasis')
  }

  return classes.join(' ')
})

const bodyClasses = computed(() => {
  const classes = []

  if (props.collapsible) {
    classes.push('collapse')
    if (isExpanded.value) classes.push('show')
  }

  if (props.centerContent) classes.push('text-center')
  if (props.noPadding) classes.push('p-0')

  return classes.join(' ')
})

const footerClasses = computed(() => {
  const classes = []

  if (props.emphasis && props.variant === 'plan') {
    classes.push('border-emphasis')
  }

  return classes.join(' ')
})

const toggleCollapse = () => {
  if (props.collapsible) {
    isExpanded.value = !isExpanded.value

    // Save state to session storage if storageKey is provided
    if (props.storageKey) {
      sessionStorage.setItem(`card-collapse-${props.storageKey}`, isExpanded.value.toString())
    }
  }
}
</script>

<style scoped>
.standard-card {
  margin-bottom: 1rem;
}

.card {
  border: 1px solid #e9ecef;
  border-radius: 0.5rem;
  transition: all 0.2s ease;
}

/* Shadow variants */
.shadow-none {
  box-shadow: none !important;
}

.shadow-sm {
  box-shadow: 0 0.125rem 0.25rem rgba(0, 0, 0, 0.075);
}

.shadow-md {
  box-shadow: 0 0.25rem 0.5rem rgba(0, 0, 0, 0.1);
}

.shadow-lg {
  box-shadow: 0 0.5rem 1rem rgba(0, 0, 0, 0.15);
}

/* Header */
.card-header {
  background-color: #f8f9fa;
  border-bottom: 1px solid #e9ecef;
  padding: 1rem 1.25rem;
  border-radius: 0.5rem 0.5rem 0 0;
}

.header-content {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.collapsible-header:hover {
  background-color: #e9ecef;
}

.card-title {
  font-size: 1.25rem;
  font-weight: 600;
  color: #2c3e50;
  margin: 0;
}

/* Body */
.card-body {
  padding: 1.25rem;
}

.card-body.p-0 {
  padding: 0 !important;
}

/* Footer */
.card-footer {
  background-color: #f8f9fa;
  border-top: 1px solid #e9ecef;
  padding: 0.75rem 1.25rem;
  border-radius: 0 0 0.5rem 0.5rem;
}

/* Actions */
.card-actions {
  margin-top: 1.5rem;
  padding-top: 1rem;
  border-top: 1px solid #e9ecef;
}

/* Info Notice */
.augmentation-notice {
  font-size: 0.9rem;
  background: #f8fafc;
  padding: 0.5rem 0.75rem;
  border-radius: 0.375rem;
  border-left: 3px solid #4f46e5;
}

.augmentation-notice i {
  font-size: 1rem;
}

.augmentation-notice a {
  color: #4f46e5 !important;
  text-decoration: none;
}

.augmentation-notice a:hover {
  text-decoration: underline;
}

/* Variant: Stats Card */
.stats-card {
  border: 1px solid #e5e7eb;
  background: #ffffff;
  transition: all 0.2s ease;
}

.stats-card:hover {
  border-color: #d1d5db;
  box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 2px 4px -1px rgba(0, 0, 0, 0.03);
}

.stats-card .card-header {
  background: linear-gradient(135deg, #f9fafb 0%, #f3f4f6 100%);
  border-bottom: 1px solid #e5e7eb;
  padding: 1rem 1.25rem;
}

.stats-card .card-title {
  color: #374151;
  font-size: 0.875rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.025em;
}

.stats-card .card-body {
  padding: 1.5rem 1.25rem;
  background: #ffffff;
}

/* Variant: Plan Card */
.plan-card {
  border: 1px solid #dee2e6;
  border-radius: 0.75rem;
  margin-bottom: 1.5rem;
  transition: all 0.2s ease;
}

.plan-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
}

.plan-card .card-header {
  background: #f8f9fa;
  border-bottom: 1px solid #eaecef;
  padding: 1.25rem;
  border-radius: 0.75rem 0.75rem 0 0;
}

.plan-card .card-body {
  padding: 1.5rem;
  display: flex;
  flex-direction: column;
  min-height: 300px;
}

.plan-emphasis {
  border-color: #6c757d !important;
}

.bg-emphasis {
  background-color: #6c757d !important;
}

.text-emphasis {
  color: #fff !important;
}

.text-emphasis .card-title {
  color: #fff !important;
}

.border-emphasis {
  border-color: #6c757d !important;
}

/* Variant: Modal Card */
.modal-card {
  background-color: #fff;
  border: 1px solid #dee2e6;
  border-radius: 0.5rem;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
}

.modal-card .card-header {
  padding: 1.25rem 1.5rem;
  background-color: #f8f9fa;
  border-bottom: 1px solid #dee2e6;
  border-radius: 0.5rem 0.5rem 0 0;
}

.modal-card .card-header .card-title {
  font-size: 1.1rem;
  font-weight: 600;
  color: #495057;
}

.modal-card .card-body {
  padding: 1.5rem;
}

/* Variant: Settings Card */
.settings-card {
  border: 1px solid #e5e9f2;
  border-radius: 0.75rem;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
  transition: box-shadow 0.2s ease;
}

.settings-card:hover {
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
}

.settings-card .card-header {
  background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);
  border-bottom: 1px solid #e5e9f2;
  border-radius: 0.75rem 0.75rem 0 0;
}

.settings-card .card-body {
  background: #ffffff;
}

/* Collapsible animation */
.collapse {
  display: none;
}

.collapse.show {
  display: block;
}

/* Responsive adjustments */
@media (max-width: 768px) {
  .header-content {
    flex-direction: column;
    align-items: flex-start;
    gap: 0.5rem;
  }

  .header-actions {
    width: 100%;
    justify-content: flex-end;
  }
}
</style>