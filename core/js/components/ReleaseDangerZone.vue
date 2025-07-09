<template>
  <StandardCard
    title="Danger Zone"
    variant="dangerzone"
    :collapsible="true"
    :defaultExpanded="false"
    storageKey="release-danger-zone"
    infoIcon="fas fa-exclamation-triangle"
  >
    <!-- Delete Release Section -->
    <div class="danger-section delete-section">
      <div class="section-header">
        <div class="section-icon delete-icon">
          <i class="fas fa-trash-alt"></i>
        </div>
        <div class="section-content">
          <h6 class="section-title">Delete Release</h6>
          <p class="section-description">Permanently remove this release and all associated artifacts</p>
        </div>
      </div>
      <button
        class="btn btn-danger modern-btn delete-btn"
        @click.prevent="showDeleteConfirmation"
      >
        <i class="fas fa-trash-alt me-2"></i>
        Delete Release
      </button>
    </div>

    <!-- Delete Confirmation Modal -->
    <DeleteConfirmationModal
      v-model:show="showConfirmModal"
      title="Delete Release"
      message="Are you sure you want to delete the release"
      :item-name="releaseName"
      warning-message="This action cannot be undone and will permanently remove the release and all its artifacts from the system."
      confirm-text="Delete Release"
      @confirm="handleDeleteConfirm"
      @cancel="hideDeleteConfirmation"
    />
  </StandardCard>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import StandardCard from './StandardCard.vue'
import DeleteConfirmationModal from './DeleteConfirmationModal.vue'
import $axios from '../utils'
import { showSuccess, showError } from '../alerts'

interface Props {
  releaseId: string
  productId: string
  releaseName: string
  csrfToken: string
}

const props = defineProps<Props>()

const showConfirmModal = ref(false)

const showDeleteConfirmation = (): void => {
  showConfirmModal.value = true
}

const hideDeleteConfirmation = (): void => {
  showConfirmModal.value = false
}

const handleDeleteConfirm = async (): Promise<void> => {
  try {
    const response = await $axios.delete(`/api/v1/products/${props.productId}/releases/${props.releaseId}`)

    if (response.status === 204) {
      showSuccess('Release deleted successfully!')
      // Redirect to product releases page after successful deletion
      window.location.href = `/product/${props.productId}/releases/`
    }
  } catch (error) {
    console.error('Error deleting release:', error)
    showError('Failed to delete release. Please try again.')
  } finally {
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
</style>