<template>
  <div class="public-card" :class="[`public-card--${variant}`, `public-card--${size}`, { 'public-card--hoverable': hoverable }]">
    <!-- Card Header -->
    <div v-if="title || subtitle || $slots.header" class="public-card-header">
      <div class="public-card-header-content">
        <div v-if="title || subtitle" class="public-card-title-section">
          <h3 v-if="title" class="public-card-title">
            <i v-if="icon" :class="icon" class="public-card-icon"></i>
            {{ title }}
          </h3>
          <p v-if="subtitle" class="public-card-subtitle">{{ subtitle }}</p>
        </div>
        <div v-if="$slots.header" class="public-card-header-actions">
          <slot name="header"></slot>
        </div>
      </div>
    </div>

    <!-- Card Body -->
    <div class="public-card-body" :class="{ 'public-card-body--padded': padded }">
      <slot></slot>
    </div>

    <!-- Card Footer -->
    <div v-if="$slots.footer" class="public-card-footer">
      <slot name="footer"></slot>
    </div>
  </div>
</template>

<script setup lang="ts">
interface Props {
  title?: string
  subtitle?: string
  icon?: string
  variant?: 'default' | 'primary' | 'secondary' | 'success' | 'warning' | 'error' | 'info'
  size?: 'sm' | 'md' | 'lg'
  hoverable?: boolean
  padded?: boolean
}

withDefaults(defineProps<Props>(), {
  title: '',
  subtitle: '',
  icon: '',
  variant: 'default',
  size: 'md',
  hoverable: false,
  padded: true
})
</script>

<style scoped>
.public-card {
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05), 0 1px 2px rgba(0, 0, 0, 0.02);
  transition: all 0.2s ease;
  overflow: hidden;
}

.public-card--hoverable:hover {
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08), 0 2px 8px rgba(0, 0, 0, 0.04);
  transform: translateY(-1px);
  border-color: rgba(var(--brand-color-rgb), 0.3);
}

/* Card Variants */
.public-card--primary {
  border-color: var(--brand-color);
  box-shadow: 0 1px 3px rgba(var(--brand-color-rgb), 0.12), 0 1px 2px rgba(var(--brand-color-rgb), 0.08);
}

.public-card--primary .public-card-header {
  background: var(--brand-color);
  color: white;
  border-bottom-color: rgba(255, 255, 255, 0.15);
}

.public-card--primary .public-card-icon {
  color: rgba(255, 255, 255, 0.9);
}

.public-card--primary .public-card-title {
  color: white;
}

.public-card--primary .public-card-subtitle {
  color: rgba(255, 255, 255, 0.85);
}

.public-card--secondary {
  border-color: var(--accent-color);
}

.public-card--secondary .public-card-header {
  background: linear-gradient(135deg, var(--accent-color) 0%, var(--accent-color-dark) 100%);
  color: white;
}

.public-card--success {
  border-color: #10b981;
}

.public-card--success .public-card-header {
  background: linear-gradient(135deg, #10b981 0%, #059669 100%);
  color: white;
}

.public-card--warning {
  border-color: #f59e0b;
}

.public-card--warning .public-card-header {
  background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%);
  color: white;
}

.public-card--error {
  border-color: #ef4444;
}

.public-card--error .public-card-header {
  background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%);
  color: white;
}

.public-card--info {
  border-color: #3b82f6;
}

.public-card--info .public-card-header {
  background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);
  color: white;
}

/* Card Sizes */
.public-card--sm {
  border-radius: var(--radius-md);
}

.public-card--sm .public-card-header {
  padding: 0.75rem 1rem;
}

.public-card--sm .public-card-body {
  padding: 1rem;
}

.public-card--sm .public-card-title {
  font-size: 1rem;
}

.public-card--md .public-card-header {
  padding: 1rem 1.5rem;
}

.public-card--md .public-card-body {
  padding: 1.5rem;
}

.public-card--md .public-card-title {
  font-size: 1.125rem;
}

.public-card--lg .public-card-header {
  padding: 1.5rem 2rem;
}

.public-card--lg .public-card-body {
  padding: 2rem;
}

.public-card--lg .public-card-title {
  font-size: 1.25rem;
}

/* Card Header */
.public-card-header {
  background: var(--bg-tertiary);
  border-bottom: 1px solid var(--border-color);
  position: relative;
}

.public-card-header::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: linear-gradient(135deg, transparent 0%, rgba(255, 255, 255, 0.1) 100%);
  pointer-events: none;
}

.public-card-header-content {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  position: relative;
  z-index: 1;
}

.public-card-title-section {
  flex: 1;
}

.public-card-title {
  margin: 0;
  font-weight: 600;
  color: var(--text-primary);
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.public-card-icon {
  opacity: 0.8;
}

.public-card-subtitle {
  margin: 0.25rem 0 0 0;
  font-size: 0.875rem;
  color: var(--text-secondary);
  opacity: 0.9;
}

.public-card-header-actions {
  flex-shrink: 0;
}

/* Card Body */
.public-card-body {
  color: var(--text-primary);
}

.public-card-body--padded {
  padding: 1.5rem;
}

.public-card-body:not(.public-card-body--padded) {
  padding: 0;
}

/* Card Footer */
.public-card-footer {
  background: var(--bg-tertiary);
  border-top: 1px solid var(--border-color);
  padding: 1rem 1.5rem;
  color: var(--text-secondary);
}

/* Responsive Design */
@media (max-width: 768px) {
  .public-card-header-content {
    flex-direction: column;
    align-items: flex-start;
    gap: 0.75rem;
  }

  .public-card-header-actions {
    width: 100%;
  }

  .public-card--lg .public-card-header,
  .public-card--lg .public-card-body {
    padding: 1.5rem;
  }

  .public-card--md .public-card-header,
  .public-card--md .public-card-body {
    padding: 1rem;
  }
}

/* Dark mode adjustments */
@media (prefers-color-scheme: dark) {
  .public-card {
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.3);
  }

  .public-card--hoverable:hover {
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.4);
  }
}
</style>