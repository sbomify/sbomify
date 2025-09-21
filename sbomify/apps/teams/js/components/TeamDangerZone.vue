<template>
  <StandardCard
    title="Danger Zone"
    variant="dangerzone"
    :collapsible="true"
    :defaultExpanded="false"
    storageKey="team-danger-zone"
    infoIcon="fas fa-exclamation-triangle"
  >
    <!-- Delete Team Section -->
    <div class="danger-section delete-section" :class="{ 'warning-section': isDefaultTeam }">
      <div class="section-header">
                  <div class="section-icon" :class="isDefaultTeam ? 'warning-icon' : 'delete-icon'">
            <i :class="isDefaultTeam ? 'fas fa-exclamation-triangle' : 'fas fa-trash-alt'"></i>
          </div>
        <div class="section-content">
          <h6 class="section-title">Delete Workspace</h6>
          <p v-if="!isDefaultTeam" class="section-description">Permanently remove this workspace and all associated data</p>
          <p v-else class="section-description">
            <i class="fas fa-exclamation-triangle me-1 text-warning"></i>
            Cannot delete the default workspace. Please set another workspace as default first.
          </p>
        </div>
      </div>
      <button
        :id="`del_${teamKey}`"
        class="btn btn-danger modern-btn delete-btn"
        :disabled="isDefaultTeam"
        :class="{ 'disabled-btn': isDefaultTeam }"
        @click.prevent="showDeleteConfirmation"
      >
        <i class="fas fa-trash-alt me-2"></i>
        Delete Workspace
      </button>
    </div>

    <!-- Delete Confirmation Modal -->
    <DeleteConfirmationModal
      v-model:show="showConfirmModal"
      title="Delete Workspace"
      message="Are you sure you want to delete the workspace"
      :item-name="teamName"
      warning-message="This action cannot be undone and will permanently remove the workspace from the system."
      confirm-text="Delete Workspace"
      @confirm="handleDeleteConfirm"
      @cancel="hideDeleteConfirmation"
    />
  </StandardCard>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import StandardCard from '../../../core/js/components/StandardCard.vue'
import DeleteConfirmationModal from '../../../core/js/components/DeleteConfirmationModal.vue'

const props = defineProps<{
  teamKey: string
  teamName: string
  csrfToken: string
  isDefaultTeam: string
}>()

const showConfirmModal = ref(false)

// Convert string to boolean
const isDefaultTeam = computed(() => props.isDefaultTeam === 'true')

const showDeleteConfirmation = (): void => {
  if (isDefaultTeam.value) {
    return // Don't show modal for default teams
  }
  showConfirmModal.value = true
}

const hideDeleteConfirmation = (): void => {
  showConfirmModal.value = false
}

const handleDeleteConfirm = (): void => {
  // Navigate to the delete URL
  window.location.href = `/workspace/delete/${props.teamKey}`
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

.warning-section {
  background: linear-gradient(135deg, #fef9e7 0%, #fef3c7 100%) !important;
  border-bottom-color: #f59e0b !important;
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

.warning-icon {
  background: linear-gradient(135deg, #f59e0b, #d97706);
  color: white;
  box-shadow: 0 2px 4px rgba(245, 158, 11, 0.3);
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

.modern-btn:focus {
  outline: none;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
}

.delete-btn {
  background: linear-gradient(135deg, #ef4444, #dc2626);
  color: white;
  box-shadow: 0 2px 4px rgba(239, 68, 68, 0.3);
}

.delete-btn:hover {
  background: linear-gradient(135deg, #dc2626, #b91c1c);
  transform: translateY(-1px);
  box-shadow: 0 4px 8px rgba(239, 68, 68, 0.4);
}

.delete-btn:active {
  transform: translateY(0);
  box-shadow: 0 2px 4px rgba(239, 68, 68, 0.3);
}

.disabled-btn {
  background: linear-gradient(135deg, #9ca3af, #6b7280) !important;
  color: #d1d5db !important;
  cursor: not-allowed !important;
  opacity: 0.6;
}

.disabled-btn:hover {
  background: linear-gradient(135deg, #9ca3af, #6b7280) !important;
  transform: none !important;
  box-shadow: 0 2px 4px rgba(156, 163, 175, 0.3) !important;
}

/* Responsive Design */
@media (max-width: 768px) {
  .section-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 0.75rem;
  }

  .section-icon {
    align-self: flex-start;
  }

  .modern-btn {
    padding: 0.625rem 1.25rem;
    font-size: 0.85rem;
    width: 100%;
    justify-content: center;
  }
}
</style>