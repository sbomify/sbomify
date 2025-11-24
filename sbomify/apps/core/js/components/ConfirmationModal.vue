<template>
  <teleport to="body">
    <div
      v-if="show"
      ref="modalElement"
      class="confirm-modal-overlay"
      tabindex="-1"
      @click="handleOverlayClick"
      @keydown="handleKeydown"
    >
      <div class="confirm-modal" :class="`confirm-modal--${variant}`" @click.stop>
        <div class="confirm-modal-header">
          <div class="confirm-modal-icon">
            <i :class="iconClass"></i>
          </div>
          <h3 class="confirm-modal-title">{{ title }}</h3>
          <button
            type="button"
            class="confirm-modal-close"
            :disabled="loading"
            @click="handleCancel"
          >
            <i class="fas fa-times"></i>
          </button>
        </div>

        <div class="confirm-modal-body">
          <p class="confirm-modal-message">
            {{ message }}
          </p>
          <p v-if="description" class="confirm-modal-description">
            {{ description }}
          </p>
        </div>

        <div class="confirm-modal-footer">
          <button
            ref="cancelButton"
            type="button"
            class="confirm-modal-button confirm-modal-button--secondary"
            :disabled="loading"
            @click="handleCancel"
          >
            {{ cancelText }}
          </button>
          <button
            ref="confirmButton"
            type="button"
            class="confirm-modal-button"
            :class="`confirm-modal-button--${variant}`"
            :disabled="loading"
            @click="handleConfirm"
          >
            <i v-if="loading" class="fas fa-spinner fa-spin me-2"></i>
            <i v-else class="fas fa-check me-2"></i>
            {{ confirmText }}
          </button>
        </div>
      </div>
    </div>
  </teleport>
</template>

<script setup lang="ts">
import { ref, watch, nextTick, computed } from 'vue'

interface Props {
  show: boolean
  title?: string
  message: string
  description?: string
  cancelText?: string
  confirmText?: string
  loading?: boolean
  variant?: 'danger' | 'warning' | 'info' | 'primary'
  icon?: string
  preventEscapeClose?: boolean
  preventOverlayClose?: boolean
}

interface Emits {
  (event: 'update:show', value: boolean): void
  (event: 'confirm'): void
  (event: 'cancel'): void
}

const props = withDefaults(defineProps<Props>(), {
  title: 'Confirm Action',
  cancelText: 'Cancel',
  confirmText: 'Confirm',
  loading: false,
  variant: 'primary',
  preventEscapeClose: false,
  preventOverlayClose: false
})

const emit = defineEmits<Emits>()

const iconClass = computed(() => {
  if (props.icon) return props.icon
  switch (props.variant) {
    case 'danger': return 'fas fa-exclamation-triangle'
    case 'warning': return 'fas fa-exclamation-circle'
    case 'info': return 'fas fa-info-circle'
    default: return 'fas fa-question-circle'
  }
})

// Modal element refs
const modalElement = ref<HTMLElement>()
const cancelButton = ref<HTMLButtonElement>()
const confirmButton = ref<HTMLButtonElement>()

const handleCancel = (): void => {
  if (props.loading) return
  emit('update:show', false)
  emit('cancel')
}

const handleConfirm = (): void => {
  emit('confirm')
}

const handleOverlayClick = (): void => {
  if (!props.preventOverlayClose) {
    handleCancel()
  }
}

const handleKeydown = (event: KeyboardEvent): void => {
  if (event.key === 'Escape' && !props.preventEscapeClose) {
    event.preventDefault()
    handleCancel()
  } else if (event.key === 'Enter') {
    event.preventDefault()
    handleConfirm()
  }
}

// Focus management for modal
watch(() => props.show, async (newValue) => {
  if (newValue) {
    await nextTick()
    modalElement.value?.focus()
  }
})
</script>

<style scoped>
.confirm-modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.6);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1050;
  padding: 1rem;
  animation: fadeIn 0.15s ease-out;
}

.confirm-modal {
  background: #ffffff;
  border-radius: 12px;
  box-shadow:
    0 20px 25px -5px rgba(0, 0, 0, 0.1),
    0 10px 10px -5px rgba(0, 0, 0, 0.04);
  max-width: 500px;
  width: 100%;
  max-height: 90vh;
  overflow: hidden;
  animation: slideIn 0.15s ease-out;
}

.confirm-modal-header {
  padding: 1.5rem 1.5rem 1rem;
  display: flex;
  align-items: flex-start;
  gap: 1rem;
  position: relative;
}

.confirm-modal-icon {
  flex-shrink: 0;
  width: 3rem;
  height: 3rem;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1.25rem;
}

/* Variant Styles for Icon */
.confirm-modal--danger .confirm-modal-icon {
  background: #fef2f2;
  border: 2px solid #fecaca;
  color: #dc2626;
}

.confirm-modal--warning .confirm-modal-icon {
  background: #fffbeb;
  border: 2px solid #fde68a;
  color: #d97706;
}

.confirm-modal--info .confirm-modal-icon {
  background: #eff6ff;
  border: 2px solid #bfdbfe;
  color: #2563eb;
}

.confirm-modal--primary .confirm-modal-icon {
  background: #f0f9ff;
  border: 2px solid #bae6fd;
  color: #0284c7;
}

.confirm-modal-title {
  flex: 1;
  margin: 0;
  font-size: 1.25rem;
  font-weight: 600;
  color: #111827;
  line-height: 1.4;
  padding-top: 0.25rem;
}

.confirm-modal-close {
  position: absolute;
  top: 1.5rem;
  right: 1.5rem;
  background: none;
  border: none;
  color: #6b7280;
  cursor: pointer;
  padding: 0.5rem;
  border-radius: 0.375rem;
  font-size: 1rem;
  line-height: 1;
  transition: all 0.15s ease;
}

.confirm-modal-close:hover:not(:disabled) {
  background: #f3f4f6;
  color: #374151;
}

.confirm-modal-body {
  padding: 0 1.5rem 1.5rem;
}

.confirm-modal-message {
  margin: 0;
  font-size: 0.95rem;
  color: #374151;
  line-height: 1.5;
}

.confirm-modal-description {
  margin: 0.5rem 0 0;
  font-size: 0.875rem;
  color: #6b7280;
  line-height: 1.4;
}

.confirm-modal-footer {
  padding: 1.5rem;
  background: #f9fafb;
  border-top: 1px solid #e5e7eb;
  display: flex;
  gap: 0.75rem;
  justify-content: flex-end;
}

.confirm-modal-button {
  padding: 0.625rem 1.25rem;
  border-radius: 0.5rem;
  font-size: 0.875rem;
  font-weight: 500;
  border: 1px solid transparent;
  cursor: pointer;
  transition: all 0.15s ease;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 80px;
}

.confirm-modal-button:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.confirm-modal-button--secondary {
  background: #ffffff;
  color: #374151;
  border-color: #d1d5db;
}

.confirm-modal-button--secondary:hover:not(:disabled) {
  background: #f9fafb;
  border-color: #9ca3af;
}

/* Variant Styles for Confirm Button */
.confirm-modal-button--danger {
  background: #dc2626;
  color: #ffffff;
}
.confirm-modal-button--danger:hover:not(:disabled) { background: #b91c1c; }

.confirm-modal-button--warning {
  background: #d97706;
  color: #ffffff;
}
.confirm-modal-button--warning:hover:not(:disabled) { background: #b45309; }

.confirm-modal-button--info {
  background: #2563eb;
  color: #ffffff;
}
.confirm-modal-button--info:hover:not(:disabled) { background: #1d4ed8; }

.confirm-modal-button--primary {
  background: #0284c7;
  color: #ffffff;
}
.confirm-modal-button--primary:hover:not(:disabled) { background: #0369a1; }

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

@keyframes slideIn {
  from { opacity: 0; transform: translate3d(0, -1rem, 0) scale(0.95); }
  to { opacity: 1; transform: translate3d(0, 0, 0) scale(1); }
}

/* Dark mode support */
@media (prefers-color-scheme: dark) {
  .confirm-modal {
    background: #1f2937;
    color: #f9fafb;
  }
  .confirm-modal-title { color: #f9fafb; }
  .confirm-modal-close { color: #9ca3af; }
  .confirm-modal-close:hover:not(:disabled) { background: #374151; color: #d1d5db; }
  .confirm-modal-message { color: #d1d5db; }
  .confirm-modal-description { color: #9ca3af; }
  .confirm-modal-footer { background: #111827; border-top-color: #374151; }
  .confirm-modal-button--secondary { background: #374151; color: #e5e7eb; border-color: #4b5563; }
  .confirm-modal-button--secondary:hover:not(:disabled) { background: #4b5563; border-color: #6b7280; }
}
</style>
