<template>
  <teleport to="body">
    <div
      v-if="show"
      ref="modalElement"
      class="delete-modal-overlay"
      tabindex="-1"
      @click="handleOverlayClick"
      @keydown="handleKeydown"
    >
      <div class="delete-modal" @click.stop>
        <div class="delete-modal-header">
          <div class="delete-modal-icon">
            <i class="fas fa-exclamation-triangle"></i>
          </div>
          <h3 class="delete-modal-title">{{ title }}</h3>
          <button
            type="button"
            class="delete-modal-close"
            :disabled="loading"
            @click="handleCancel"
          >
            <i class="fas fa-times"></i>
          </button>
        </div>

        <div class="delete-modal-body">
          <p class="delete-modal-message">
            {{ message }}
            <span v-if="itemName" class="delete-modal-name">{{ itemName }}</span>{{ messageSuffix }}
          </p>
          <p class="delete-modal-warning">
            {{ warningMessage }}
          </p>
        </div>

        <div class="delete-modal-footer">
          <button
            ref="cancelButton"
            type="button"
            class="delete-modal-button delete-modal-button--secondary"
            :disabled="loading"
            @click="handleCancel"
          >
            {{ cancelText }}
          </button>
          <button
            ref="confirmButton"
            type="button"
            class="delete-modal-button delete-modal-button--danger"
            :disabled="loading"
            @click="handleConfirm"
          >
            <i v-if="loading" class="fas fa-spinner fa-spin me-2"></i>
            <i v-else class="fas fa-trash me-2"></i>
            {{ confirmText }}
          </button>
        </div>
      </div>
    </div>
  </teleport>
</template>

<script setup lang="ts">
import { ref, watch, nextTick } from 'vue'

interface Props {
  show: boolean
  title?: string
  message?: string
  messageSuffix?: string
  itemName?: string
  warningMessage?: string
  cancelText?: string
  confirmText?: string
  loading?: boolean
  preventEscapeClose?: boolean
  preventOverlayClose?: boolean
}

interface Emits {
  (event: 'update:show', value: boolean): void
  (event: 'confirm'): void
  (event: 'cancel'): void
}

const props = withDefaults(defineProps<Props>(), {
  title: 'Confirm Delete',
  message: 'Are you sure you want to delete',
  messageSuffix: '?',
  warningMessage: 'This action cannot be undone and will permanently remove the item from the system.',
  cancelText: 'Cancel',
  confirmText: 'Delete',
  loading: false,
  preventEscapeClose: false,
  preventOverlayClose: false
})

const emit = defineEmits<Emits>()

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
/* Modern Delete Modal Styles */
.delete-modal-overlay {
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

.delete-modal {
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

.delete-modal-header {
  padding: 1.5rem 1.5rem 1rem;
  display: flex;
  align-items: flex-start;
  gap: 1rem;
  position: relative;
}

.delete-modal-icon {
  flex-shrink: 0;
  width: 3rem;
  height: 3rem;
  background: #fef2f2;
  border: 2px solid #fecaca;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #dc2626;
  font-size: 1.25rem;
}

.delete-modal-title {
  flex: 1;
  margin: 0;
  font-size: 1.25rem;
  font-weight: 600;
  color: #111827;
  line-height: 1.4;
  padding-top: 0.25rem;
}

.delete-modal-close {
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

.delete-modal-close:hover:not(:disabled) {
  background: #f3f4f6;
  color: #374151;
}

.delete-modal-close:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.delete-modal-body {
  padding: 0 1.5rem 1.5rem;
}

.delete-modal-message {
  margin: 0 0 0.75rem;
  font-size: 0.95rem;
  color: #374151;
  line-height: 1.5;
}

.delete-modal-name {
  font-weight: 600;
  color: #111827;
  word-break: break-all;
}

.delete-modal-warning {
  margin: 0;
  font-size: 0.875rem;
  color: #6b7280;
  line-height: 1.4;
}

.delete-modal-footer {
  padding: 1.5rem;
  background: #f9fafb;
  border-top: 1px solid #e5e7eb;
  display: flex;
  gap: 0.75rem;
  justify-content: flex-end;
}

.delete-modal-button {
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

.delete-modal-button:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.delete-modal-button--secondary {
  background: #ffffff;
  color: #374151;
  border-color: #d1d5db;
}

.delete-modal-button--secondary:hover:not(:disabled) {
  background: #f9fafb;
  border-color: #9ca3af;
}

.delete-modal-button--danger {
  background: #dc2626;
  color: #ffffff;
}

.delete-modal-button--danger:hover:not(:disabled) {
  background: #b91c1c;
}

@keyframes fadeIn {
  from {
    opacity: 0;
  }
  to {
    opacity: 1;
  }
}

@keyframes slideIn {
  from {
    opacity: 0;
    transform: translate3d(0, -1rem, 0) scale(0.95);
  }
  to {
    opacity: 1;
    transform: translate3d(0, 0, 0) scale(1);
  }
}

/* Dark mode support */
@media (prefers-color-scheme: dark) {
  .delete-modal {
    background: #1f2937;
    color: #f9fafb;
  }

  .delete-modal-title {
    color: #f9fafb;
  }

  .delete-modal-name {
    color: #e5e7eb;
  }

  .delete-modal-close {
    color: #9ca3af;
  }

  .delete-modal-close:hover:not(:disabled) {
    background: #374151;
    color: #d1d5db;
  }

  .delete-modal-message {
    color: #d1d5db;
  }

  .delete-modal-warning {
    color: #9ca3af;
  }

  .delete-modal-footer {
    background: #111827;
    border-top-color: #374151;
  }

  .delete-modal-button--secondary {
    background: #374151;
    color: #e5e7eb;
    border-color: #4b5563;
  }

  .delete-modal-button--secondary:hover:not(:disabled) {
    background: #4b5563;
    border-color: #6b7280;
  }
}
</style>