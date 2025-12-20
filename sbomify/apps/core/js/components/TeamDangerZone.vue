<template>
  <StandardCard
    title="Danger Zone"
    variant="dangerzone"
    :collapsible="true"
    :defaultExpanded="false"
    infoIcon="fas fa-exclamation-triangle"
  >
    <!-- Delete Workspace Section -->
    <div class="danger-section delete-section">
      <div class="section-header">
        <div class="section-icon delete-icon">
          <i class="fas fa-trash-alt"></i>
        </div>
        <div class="section-content">
          <h6 class="section-title">Delete Workspace</h6>
          <p class="section-description">
            Permanently remove this workspace and all its associated data.
            <span v-if="isDefaultTeam" class="text-warning d-block mt-1">
              <i class="fas fa-info-circle me-1"></i>
              You must set another workspace as default before deleting this one.
            </span>
          </p>
        </div>
      </div>
      <button
        :id="`del_${teamKey}`"
        class="btn btn-danger modern-btn delete-btn"
        :disabled="isDefaultTeam"
        @click.prevent="showDeleteConfirmation"
      >
        <i class="fas fa-trash-alt me-2"></i>
        Delete Workspace
      </button>
    </div>

    <!-- Delete Confirmation Modal - Custom implementation -->
    <teleport to="body">
      <div
        v-if="showConfirmModal"
        class="delete-modal-overlay"
        tabindex="-1"
        @click.self="hideDeleteConfirmation"
        @keydown.esc="hideDeleteConfirmation"
      >
        <div class="delete-modal" @click.stop>
          <div class="delete-modal-header">
            <div class="delete-modal-icon">
              <i class="fas fa-exclamation-triangle"></i>
            </div>
            <h3 class="delete-modal-title">Delete Workspace</h3>
            <button
              type="button"
              class="delete-modal-close"
              @click="hideDeleteConfirmation"
            >
              <i class="fas fa-times"></i>
            </button>
          </div>

          <div class="delete-modal-body">
            <p class="delete-modal-message">
              Are you sure you want to delete the workspace
              <span class="delete-modal-name">{{ teamName }}</span>?
            </p>
            <p class="delete-modal-warning">
              This action cannot be undone. All products, projects, components, SBOMs, and documents in this workspace will be permanently deleted.
            </p>
            <p class="delete-modal-confirm-text mb-2 mt-3">
              Type <strong>delete</strong> to confirm:
            </p>
            <input
              v-model="confirmText"
              type="text"
              class="form-control"
              placeholder="Type 'delete' to confirm"
              @keydown.enter="canConfirm && handleDeleteConfirm()"
            />
          </div>

          <div class="delete-modal-footer">
            <button
              type="button"
              class="delete-modal-button delete-modal-button--secondary"
              @click="hideDeleteConfirmation"
            >
              Cancel
            </button>
            <button
              type="button"
              class="delete-modal-button delete-modal-button--danger"
              :disabled="!canConfirm"
              @click="handleDeleteConfirm"
            >
              <i class="fas fa-trash me-2"></i>
              Delete Workspace
            </button>
          </div>
        </div>
      </div>
    </teleport>
  </StandardCard>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import StandardCard from './StandardCard.vue'
import { showError } from '../alerts'

const props = defineProps<{
  teamKey: string
  teamName: string
  isDefaultTeam: boolean
  csrfToken: string
}>()

const showConfirmModal = ref(false)
const confirmText = ref('')

const canConfirm = computed(() => {
  return confirmText.value.toLowerCase() === 'delete'
})

const showDeleteConfirmation = (): void => {
  if (props.isDefaultTeam) {
    showError('Cannot delete the default workspace. Please set another workspace as default first.')
    return
  }
  showConfirmModal.value = true
}

const hideDeleteConfirmation = (): void => {
  showConfirmModal.value = false
  confirmText.value = ''
}

const handleDeleteConfirm = async (): Promise<void> => {
  try {
    const form = document.createElement('form')
    form.method = 'POST'
    form.action = `/workspace/${props.teamKey}/general`
    
    const csrfInput = document.createElement('input')
    csrfInput.type = 'hidden'
    csrfInput.name = 'csrfmiddlewaretoken'
    csrfInput.value = props.csrfToken
    form.appendChild(csrfInput)
    
    const actionInput = document.createElement('input')
    actionInput.type = 'hidden'
    actionInput.name = 'action'
    actionInput.value = 'delete'
    form.appendChild(actionInput)
    
    document.body.appendChild(form)
    form.submit()
  } catch {
    showError('Failed to delete workspace. Please try again.')
    hideDeleteConfirmation()
  }
}
</script>

<style scoped>
/* Section Layout */
.danger-section {
  padding: 1.5rem;
  margin: 0 -2px;
  border-radius: 0;
  background: #fafafa;
  border: none;
  border-bottom: 1px solid #e5e5e5;
  transition: all 0.2s ease;
}

.danger-section:last-child {
  border-bottom: none;
  border-radius: 0 0 0.75rem 0.75rem !important;
  margin-bottom: -2px;
}

.danger-section:first-child:last-child {
  border-radius: 0 0 0.75rem 0.75rem !important;
  margin-bottom: -2px;
}

.danger-section:hover {
  background: #f5f5f5;
}

.delete-section {
  background: linear-gradient(135deg, #fef2f2 0%, #fee2e2 100%);
  border-bottom-color: #ef4444;
}

.delete-section:last-child {
  border-radius: 0 0 0.75rem 0.75rem !important;
  overflow: hidden;
  margin-bottom: -2px;
}

/* Section Header */
.section-header {
  display: flex;
  align-items: flex-start;
  gap: 1rem;
  margin-bottom: 1.25rem;
}

.section-icon {
  width: 2.5rem;
  height: 2.5rem;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1.1rem;
  flex-shrink: 0;
}

.delete-icon {
  background: linear-gradient(135deg, #ef4444, #dc2626);
  color: white;
  box-shadow: 0 2px 4px rgba(239, 68, 68, 0.3);
}

.section-content {
  flex: 1;
}

.section-title {
  font-size: 1.1rem;
  font-weight: 600;
  color: #374151;
  margin: 0 0 0.25rem 0;
}

.section-description {
  font-size: 0.875rem;
  color: #6b7280;
  margin: 0;
  line-height: 1.4;
}

/* Modern Buttons */
.modern-btn {
  padding: 0.75rem 1.5rem;
  font-size: 0.9rem;
  font-weight: 500;
  border-radius: 8px;
  border: none;
  transition: all 0.2s ease;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  text-decoration: none;
  cursor: pointer;
  white-space: nowrap;
}

.delete-btn {
  background: linear-gradient(135deg, #ef4444, #dc2626);
  color: white;
  box-shadow: 0 2px 4px rgba(239, 68, 68, 0.3);
  margin-top: 0.5rem;
}

.delete-btn:hover:not(:disabled) {
  background: linear-gradient(135deg, #dc2626, #b91c1c);
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(239, 68, 68, 0.4);
  color: white;
}

.modern-btn:active {
  transform: translateY(0);
}

.modern-btn i {
  font-size: 0.875rem;
}

/* Responsive Design */
@media (max-width: 768px) {
  .danger-section {
    padding: 1rem;
    margin: 0 -2px;
  }

  .section-header {
    gap: 0.75rem;
    margin-bottom: 1rem;
  }

  .section-icon {
    width: 2rem;
    height: 2rem;
    font-size: 1rem;
  }

  .delete-btn {
    width: 100%;
  }
}

/* Accessibility improvements */
.modern-btn:focus {
  outline: 2px solid transparent;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.5);
}

.modern-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
  transform: none;
}

.modern-btn:disabled:hover {
  transform: none;
  box-shadow: none;
}

/* Delete Modal Styles */
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

.delete-modal-close:hover {
  background: #f3f4f6;
  color: #374151;
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

.delete-modal-confirm-text {
  font-size: 0.875rem;
  color: #374151;
  margin: 0;
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
</style>

