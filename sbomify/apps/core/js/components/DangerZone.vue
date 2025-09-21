<template>
  <StandardCard
    title="Danger Zone"
    variant="dangerzone"
    :collapsible="true"
    :defaultExpanded="false"
    storageKey="danger-zone"
    infoIcon="fas fa-exclamation-triangle"
  >
    <!-- Transfer Component Section -->
    <div v-if="parsedIsOwner" class="danger-section transfer-section">
      <div class="section-header">
        <div class="section-icon transfer-icon">
          <i class="fas fa-exchange-alt"></i>
        </div>
        <div class="section-content">
          <h6 class="section-title">Transfer Component</h6>
          <p class="section-description">Move this component to a different team</p>
        </div>
      </div>
      <form :action="`/component/${componentId}/transfer`" method="post" class="transfer-form">
        <input type="hidden" name="csrfmiddlewaretoken" :value="csrfToken">
        <div class="mb-3">
          <label for="team_key" class="form-label">Select Team</label>
          <div class="input-group">
            <select id="team_key" name="team_key" class="form-select modern-select">
              <option value="" disabled selected>Choose a team...</option>
              <option
                v-for="(team, teamKey) in parsedUserTeams"
                :key="teamKey"
                :value="teamKey"
              >
                {{ team.name }}
              </option>
            </select>
            <button type="submit" class="btn btn-warning modern-btn transfer-btn">
              <i class="fas fa-arrow-right me-2"></i>
              Transfer
            </button>
          </div>
        </div>
      </form>
    </div>

    <!-- Divider -->
    <div v-if="parsedIsOwner" class="section-divider"></div>

    <!-- Delete Component Section -->
    <div class="danger-section delete-section">
      <div class="section-header">
        <div class="section-icon delete-icon">
          <i class="fas fa-trash-alt"></i>
        </div>
        <div class="section-content">
          <h6 class="section-title">Delete Component</h6>
          <p class="section-description">Permanently remove this component and all associated data</p>
        </div>
      </div>
      <button
        :id="`del_${componentId}`"
        class="btn btn-danger modern-btn delete-btn"
        @click.prevent="showDeleteConfirmation"
      >
        <i class="fas fa-trash-alt me-2"></i>
        Delete Component
      </button>
    </div>

    <!-- Delete Confirmation Modal -->
    <DeleteConfirmationModal
      v-model:show="showConfirmModal"
      title="Delete Component"
      message="Are you sure you want to delete the component"
      :item-name="componentName"
      warning-message="This action cannot be undone and will permanently remove the component from the system."
      confirm-text="Delete Component"
      @confirm="handleDeleteConfirm"
      @cancel="hideDeleteConfirmation"
    />
  </StandardCard>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import StandardCard from '../../../core/js/components/StandardCard.vue'
import DeleteConfirmationModal from '../../../core/js/components/DeleteConfirmationModal.vue'
import $axios from '../../../core/js/utils'
import { showSuccess, showError } from '../../../core/js/alerts'

interface Team {
  name: string
}

const props = defineProps<{
  componentId: string
  componentName: string
  isOwner: string
  userTeamsElementId?: string
  csrfToken: string
}>()

const showConfirmModal = ref(false)
const parsedIsOwner = ref(false)
const parsedUserTeams = ref<Record<string, Team>>({})

const showDeleteConfirmation = (): void => {
  showConfirmModal.value = true
}

const hideDeleteConfirmation = (): void => {
  showConfirmModal.value = false
}

const handleDeleteConfirm = async (): Promise<void> => {
  try {
    const response = await $axios.delete(`/api/v1/components/${props.componentId}`)

    if (response.status === 204) {
      showSuccess('Component deleted successfully!')
      // Redirect to components dashboard after successful deletion
      window.location.href = '/components/'
    }
  } catch (error) {
    console.error('Error deleting component:', error)
    showError('Failed to delete component. Please try again.')
  } finally {
    hideDeleteConfirmation()
  }
}

const parseProps = (): void => {
  try {
    // Parse isOwner boolean
    parsedIsOwner.value = props.isOwner === 'true'

    // Parse userTeams from JSON script element
    if (props.userTeamsElementId) {
      const element = document.getElementById(props.userTeamsElementId)
      if (element && element.textContent) {
        parsedUserTeams.value = JSON.parse(element.textContent)
      }
    }
  } catch (err) {
    console.error('Error parsing DangerZone props:', err)
    parsedIsOwner.value = false
    parsedUserTeams.value = {}
  }
}

onMounted(() => {
  parseProps()
})
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
  overflow: hidden;
  margin-bottom: -2px;
}

.danger-section:first-child:last-child {
  border-radius: 0 0 0.75rem 0.75rem !important;
  overflow: hidden;
  margin-bottom: -2px;
}

.danger-section:hover {
  background: #f5f5f5;
}

.transfer-section {
  background: linear-gradient(135deg, #fff8e1 0%, #fff3c4 100%);
  border-bottom-color: #f59e0b;
}

.delete-section {
  background: linear-gradient(135deg, #fef2f2 0%, #fee2e2 100%);
  border-bottom-color: #ef4444;
}

.delete-section:last-child,
.transfer-section:last-child {
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

.transfer-icon {
  background: linear-gradient(135deg, #f59e0b, #d97706);
  color: white;
  box-shadow: 0 2px 4px rgba(245, 158, 11, 0.3);
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

/* Divider */
.section-divider {
  height: 1px;
  background: linear-gradient(90deg, transparent, #d1d5db, transparent);
  margin: 0;
}

/* Form Styling */
.transfer-form {
  margin-top: 1rem;
}



.form-label {
  font-size: 0.875rem;
  font-weight: 500;
  color: #374151;
  margin-bottom: 0.5rem;
  display: block;
}

.input-group {
  display: flex;
  gap: 0.75rem;
  align-items: stretch;
}

.modern-select {
  flex: 1;
  min-width: 200px;
  padding: 0.75rem 1rem;
  border: 2px solid #d1d5db;
  border-radius: 8px;
  background: white;
  font-size: 0.9rem;
  color: #374151;
  transition: all 0.2s ease;
  appearance: none;
  background-image: url("data:image/svg+xml,%3csvg xmlns='http://www.w3.org/2000/svg' fill='none' viewBox='0 0 20 20'%3e%3cpath stroke='%236b7280' stroke-linecap='round' stroke-linejoin='round' stroke-width='1.5' d='m6 8 4 4 4-4'/%3e%3c/svg%3e");
  background-position: right 0.75rem center;
  background-repeat: no-repeat;
  background-size: 1.5em 1.5em;
  padding-right: 3rem;
}

.modern-select:focus {
  outline: none;
  border-color: #f59e0b;
  box-shadow: 0 0 0 3px rgba(245, 158, 11, 0.1);
}

.modern-select:hover {
  border-color: #9ca3af;
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

.transfer-btn {
  background: linear-gradient(135deg, #f59e0b, #d97706);
  color: white;
  box-shadow: 0 2px 4px rgba(245, 158, 11, 0.3);
}

.transfer-btn:hover {
  background: linear-gradient(135deg, #d97706, #b45309);
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(245, 158, 11, 0.4);
  color: white;
}

.delete-btn {
  background: linear-gradient(135deg, #ef4444, #dc2626);
  color: white;
  box-shadow: 0 2px 4px rgba(239, 68, 68, 0.3);
  margin-top: 0.5rem;
}

.delete-btn:hover {
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

  .input-group {
    flex-direction: column;
    gap: 0.75rem;
  }

  .modern-select {
    min-width: unset;
  }

  .transfer-btn,
  .delete-btn {
    width: 100%;
  }
}

/* Accessibility improvements */
.modern-btn:focus {
  outline: 2px solid transparent;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.5);
}

.modern-select:disabled {
  background-color: #f3f4f6;
  color: #9ca3af;
  cursor: not-allowed;
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
</style>