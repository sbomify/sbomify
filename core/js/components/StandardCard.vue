<template>
  <div class="standard-card mt-3">
    <div class="card">
      <div
        v-if="title"
        class="card-header"
        :class="{ 'collapsible-header': collapsible }"
      >
        <h4
          class="card-title mb-0"
          :style="collapsible ? 'cursor: pointer;' : ''"
          @click="collapsible ? toggleCollapse() : null"
        >
          {{ title }}
          <i v-if="collapsible" class="fas ms-2" :class="isExpanded ? 'fa-chevron-down' : 'fa-chevron-right'"></i>
        </h4>
      </div>

      <div :id="collapseId" class="card-body" :class="{ 'collapse': collapsible, 'show': isExpanded }">
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
      <div v-if="hasFooter" class="card-footer">
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
}

const props = withDefaults(defineProps<Props>(), {
  title: '',
  collapsible: false,
  defaultExpanded: true,
  infoIcon: 'fas fa-info-circle',
  storageKey: ''
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
  box-shadow: 0 0.125rem 0.25rem rgba(0, 0, 0, 0.075);
}

.card-header {
  background-color: #f8f9fa;
  border-bottom: 1px solid #e9ecef;
  padding: 1rem 1.25rem;
}

.collapsible-header:hover {
  background-color: #e9ecef;
}

.card-title {
  font-size: 1.25rem;
  font-weight: 600;
  color: #2c3e50;
}

.card-body {
  padding: 1.25rem;
}

.card-actions {
  margin-top: 1.5rem;
  padding-top: 1rem;
  border-top: 1px solid #e9ecef;
}

.card-footer {
  background-color: #f8f9fa;
  border-top: 1px solid #e9ecef;
  padding: 0.75rem 1.25rem;
}

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

/* Collapsible animation */
.collapse {
  display: none;
}

.collapse.show {
  display: block;
}
</style>