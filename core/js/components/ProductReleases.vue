<template>
  <!-- Always use StandardCard for consistent styling -->
  <StandardCard
    title="Releases"
    variant="default"
    shadow="sm"
  >
    <template #header-actions>
      <!-- Public View: Show View All link -->
      <a
        v-if="isPublicView && viewAllUrl"
        :href="viewAllUrl"
        class="btn btn-outline-primary"
      >
        View All <i class="fas fa-arrow-right ms-1"></i>
      </a>

      <!-- Private View: Show Add Release button -->
      <button
        v-else-if="hasCrudPermissions && !isPublicView"
        class="btn btn-primary px-4"
        data-bs-toggle="modal"
        data-bs-target="#addReleaseModal"
      >
        <i class="fas fa-plus me-2"></i>Add Release
      </button>
    </template>

    <!-- Loading State -->
    <div v-if="isLoading" class="dashboard-empty">
      <div class="spinner-border text-primary" role="status">
        <span class="visually-hidden">Loading...</span>
      </div>
      <p class="mb-0 mt-2">Loading releases...</p>
    </div>

    <!-- Error State -->
    <div v-else-if="error" class="alert alert-danger">
      <p class="mb-0">Failed to load releases. Please try refreshing the page.</p>
    </div>

    <!-- Empty State -->
    <div v-else-if="!hasData" class="dashboard-empty">
      <div class="empty-icon">
        <i class="fas fa-tag"></i>
      </div>
      <h5>No releases yet</h5>
      <p class="mb-3 text-muted">{{ isPublicView ? 'This product doesn\'t have any releases yet.' : 'Create your first release to get started' }}</p>
      <button
        v-if="hasCrudPermissions && !isPublicView"
        class="btn btn-primary"
        data-bs-toggle="modal"
        data-bs-target="#addReleaseModal"
      >
        <i class="fas fa-plus me-2"></i>Create Release
      </button>
    </div>

    <!-- Releases List -->
    <div v-else class="releases-list">
      <div
        v-for="release in displayedReleases"
        :key="release.id"
        class="release-item"
      >
        <div class="release-header">
          <div class="release-info">
            <div class="release-title">
              <a
                :href="getReleaseUrl(release)"
                class="release-name"
              >
                {{ release.name }}
              </a>
              <div class="release-badges">
                <span
                  v-if="release.is_latest"
                  class="badge bg-success"
                >
                  Latest
                </span>
                <span
                  v-if="release.is_prerelease"
                  class="badge bg-warning"
                >
                  Pre-release
                </span>
                <!-- In public view, only show Public badge. In private view, show both Public/Private -->
                <span
                  v-if="isPublicView && release.is_public"
                  class="badge bg-primary"
                >
                  Public
                </span>
                <span
                  v-else-if="!isPublicView && release.is_public"
                  class="badge bg-primary"
                >
                  Public
                </span>
                <span
                  v-else-if="!isPublicView && !release.is_public"
                  class="badge bg-secondary"
                >
                  Private
                </span>
              </div>
            </div>
            <p v-if="release.description" class="release-description">
              {{ release.description }}
            </p>
          </div>
          <div class="release-actions">
            <div class="release-meta">
              <small class="text-muted">
                <i class="fas fa-calendar me-1"></i>
                {{ formatDate(release.created_at) }}
              </small>
            </div>
            <div class="action-buttons">
              <a
                v-if="release.has_sboms"
                :href="`/api/v1/releases/${release.id}/download`"
                class="btn btn-sm btn-outline-primary"
                title="Download release SBOM"
              >
                <i class="fas fa-download me-1"></i>Download
              </a>
              <div v-if="hasCrudPermissions && !release.is_latest && !isPublicView" class="crud-buttons">
                <button
                  class="btn btn-sm btn-outline-secondary"
                  title="Edit release"
                  @click="editRelease(release)"
                >
                  <i class="fas fa-edit"></i>
                </button>
                <button
                  class="btn btn-sm btn-outline-danger"
                  title="Delete release"
                  @click="deleteRelease(release)"
                >
                  <i class="fas fa-trash-alt"></i>
                </button>
              </div>
            </div>
          </div>
        </div>
        <div v-if="release.artifacts_count" class="release-summary">
          <span class="artifacts-summary">
            <i class="fas fa-puzzle-piece me-1"></i>
            {{ release.artifacts_count }} artifact{{ (release.artifacts_count || 0) === 1 ? '' : 's' }}
          </span>
        </div>
      </div>

      <!-- Show "View All" message when releases are truncated -->
      <div v-if="hasTruncatedReleases" class="view-all-notice">
        <div class="notice-content">
          <span class="notice-text">
            Showing {{ displayedReleases.length }} of {{ releases.length }} releases
          </span>
          <a :href="viewAllUrl" class="view-all-link">
            View All Releases <i class="fas fa-arrow-right ms-1"></i>
          </a>
        </div>
      </div>
    </div>

    <!-- Pagination Controls -->
    <PaginationControls
      v-if="shouldShowPagination"
      v-model:current-page="currentPage"
      v-model:page-size="pageSize"
      :total-pages="paginationMeta!.total_pages"
      :total-items="paginationMeta!.total"
      :show-page-size-selector="true"
    />

    <!-- Add Release Modal (only for private view) -->
    <div
      v-if="hasCrudPermissions && !isPublicView"
      id="addReleaseModal"
      class="modal fade"
      tabindex="-1"
    >
      <div class="modal-dialog">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title">
              {{ editingRelease ? 'Edit Release' : 'Create New Release' }}
            </h5>
            <button
              type="button"
              class="btn-close"
              data-bs-dismiss="modal"
            ></button>
          </div>
          <div class="modal-body">
            <form @submit.prevent="submitRelease">
              <div class="mb-3">
                <label for="releaseName" class="form-label">Release Name</label>
                <input
                  id="releaseName"
                  v-model="releaseForm.name"
                  type="text"
                  class="form-control"
                  required
                  placeholder="e.g., v1.0.0, 2024.1, beta-3"
                >
                <div class="form-text">Enter a unique name for this release</div>
              </div>
              <div class="mb-3">
                <label for="releaseDescription" class="form-label">Description (Optional)</label>
                <textarea
                  id="releaseDescription"
                  v-model="releaseForm.description"
                  class="form-control"
                  rows="3"
                  placeholder="Describe what's included in this release..."
                ></textarea>
              </div>
              <div class="form-check">
                <input
                  id="releaseIsPrerelease"
                  v-model="releaseForm.is_prerelease"
                  class="form-check-input"
                  type="checkbox"
                >
                <label for="releaseIsPrerelease" class="form-check-label">
                  Mark as pre-release
                </label>
                <div class="form-text">Pre-releases are typically alpha, beta, or release candidate versions</div>
              </div>
            </form>
          </div>
          <div class="modal-footer">
            <button
              type="button"
              class="btn btn-secondary"
              data-bs-dismiss="modal"
            >
              Cancel
            </button>
            <button
              type="button"
              class="btn btn-primary"
              :disabled="isSubmitting"
              @click="submitRelease"
            >
              <span v-if="isSubmitting" class="spinner-border spinner-border-sm me-2"></span>
              {{ editingRelease ? 'Update Release' : 'Create Release' }}
            </button>
          </div>
        </div>
      </div>
    </div>
  </StandardCard>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import $axios from '../utils'
import { showError, showSuccess } from '../alerts'
import { isAxiosError } from 'axios'
import StandardCard from './StandardCard.vue'
import PaginationControls from './PaginationControls.vue'

interface Release {
  id: string
  name: string
  description?: string
  is_public: boolean
  is_latest: boolean
  is_prerelease: boolean
  created_at: string
  artifacts_count?: number
  has_sboms?: boolean
}

interface ReleaseForm {
  name: string
  description: string
  is_prerelease: boolean
}

interface PaginationMeta {
  total: number
  page: number
  page_size: number
  total_pages: number
  has_previous: boolean
  has_next: boolean
}

interface Props {
  productId: string
  hasCrudPermissions?: boolean | string
  publicView?: boolean | string
  viewAllUrl?: string
  maxReleasesToShow?: number
}

const props = withDefaults(defineProps<Props>(), {
  hasCrudPermissions: false,
  publicView: false,
  viewAllUrl: '',
  maxReleasesToShow: 5
})

// State
const releases = ref<Release[]>([])
const isLoading = ref(false)
const isSubmitting = ref(false)
const error = ref<string | null>(null)
const editingRelease = ref<Release | null>(null)
const paginationMeta = ref<PaginationMeta | null>(null)
const currentPage = ref(1)
const pageSize = ref(15)

const releaseForm = ref<ReleaseForm>({
  name: '',
  description: '',
  is_prerelease: false
})

// Computed
const hasCrudPermissions = computed(() => {
  if (typeof props.hasCrudPermissions === 'string') {
    return props.hasCrudPermissions === 'true'
  }
  return props.hasCrudPermissions
})

const isPublicView = computed(() => {
  if (typeof props.publicView === 'string') {
    return props.publicView === 'true'
  }
  return props.publicView
})

const hasData = computed(() => releases.value.length > 0)

const displayedReleases = computed(() => {
  // In public view with viewAllUrl, show truncated releases
  if (isPublicView.value && props.viewAllUrl && releases.value.length > props.maxReleasesToShow) {
    return releases.value.slice(0, props.maxReleasesToShow)
  }
  // Otherwise show all releases
  return releases.value
})

const hasTruncatedReleases = computed(() => {
  return isPublicView.value && props.viewAllUrl && releases.value.length > props.maxReleasesToShow
})

// Show pagination controls only if we have pagination metadata and more than one page
const shouldShowPagination = computed(() => {
  return paginationMeta.value && paginationMeta.value.total_pages > 1 && !isPublicView.value
})

// Methods
const formatDate = (dateString: string): string => {
  return new Date(dateString).toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric'
  })
}

const getReleaseUrl = (release: Release): string => {
  if (isPublicView.value) {
    return `/public/product/${props.productId}/release/${release.id}/`
  }
  return `/product/${props.productId}/release/${release.id}/`
}

const loadReleases = async () => {
  isLoading.value = true
  error.value = null

  try {
    const params = new URLSearchParams({
      product_id: props.productId,
      page: currentPage.value.toString(),
      page_size: pageSize.value.toString()
    })

    const response = await $axios.get(`/api/v1/releases?${params}`)
    // Handle both old array format and new paginated format for backward compatibility
    if (Array.isArray(response.data)) {
      releases.value = response.data
      paginationMeta.value = null
    } else {
      releases.value = response.data.items || []
      paginationMeta.value = response.data.pagination || null
    }
  } catch (err) {
    console.error('Error loading releases:', err)
    error.value = 'Failed to load releases'

    if (isAxiosError(err)) {
      showError(err.response?.data?.detail || 'Failed to load releases')
    } else {
      showError('Failed to load releases')
    }
  } finally {
    isLoading.value = false
  }
}



const resetForm = () => {
  releaseForm.value = {
    name: '',
    description: '',
    is_prerelease: false
  }
  editingRelease.value = null
}

const editRelease = (release: Release) => {
  editingRelease.value = release
  releaseForm.value = {
    name: release.name,
    description: release.description || '',
    is_prerelease: release.is_prerelease || false
  }

  const modalElement = document.getElementById('addReleaseModal')
  if (modalElement) {
    const bootstrap = (window as unknown as { bootstrap?: { Modal: new(element: Element) => { show(): void } } }).bootstrap
    if (bootstrap && bootstrap.Modal) {
      const modal = new bootstrap.Modal(modalElement)
      modal.show()
    }
  }
}

const deleteRelease = async (release: Release) => {
  if (!confirm(`Are you sure you want to delete the release "${release.name}"? This action cannot be undone.`)) {
    return
  }

  try {
    await $axios.delete(`/api/v1/releases/${release.id}`)
    showSuccess('Release deleted successfully!')
    await loadReleases()
  } catch (err) {
    console.error('Error deleting release:', err)

    if (isAxiosError(err)) {
      showError(err.response?.data?.detail || 'Failed to delete release')
    } else {
      showError('Failed to delete release')
    }
  }
}

const submitRelease = async () => {
  if (!releaseForm.value.name.trim()) {
    showError('Release name is required')
    return
  }

  isSubmitting.value = true

  try {
    if (editingRelease.value) {
      // Update existing release using top-level API
      const data = {
        name: releaseForm.value.name.trim(),
        description: releaseForm.value.description.trim() || null,
        is_prerelease: releaseForm.value.is_prerelease
      }

      await $axios.patch(`/api/v1/releases/${editingRelease.value.id}`, data)
      showSuccess('Release updated successfully!')
    } else {
      // Create new release using top-level API
      const data = {
        name: releaseForm.value.name.trim(),
        description: releaseForm.value.description.trim() || null,
        is_prerelease: releaseForm.value.is_prerelease,
        product_id: props.productId
      }

      await $axios.post('/api/v1/releases', data)
      showSuccess('Release created successfully!')
    }

    const modalElement = document.getElementById('addReleaseModal')
    if (modalElement) {
      const bootstrap = (window as unknown as { bootstrap?: { Modal: { getInstance(element: Element): { hide(): void } | null } } }).bootstrap
      if (bootstrap && bootstrap.Modal) {
        const modal = bootstrap.Modal.getInstance(modalElement)
        modal?.hide()
      }
    }
    resetForm()
    await loadReleases()
  } catch (err) {
    console.error('Error submitting release:', err)

    if (isAxiosError(err)) {
      showError(err.response?.data?.detail || 'Failed to save release')
    } else {
      showError('Failed to save release')
    }
  } finally {
    isSubmitting.value = false
  }
}

// Event handlers
const handleModalHidden = () => {
  resetForm()
}

// Watchers for pagination changes
watch([currentPage, pageSize], () => {
  loadReleases()
})

// Lifecycle
onMounted(async () => {
  await loadReleases()

  // Set up modal event listener only for private view
  if (!isPublicView.value) {
    const modal = document.getElementById('addReleaseModal')
    if (modal) {
      modal.addEventListener('hidden.bs.modal', handleModalHidden)
    }
  }
})

// Expose methods for external use
defineExpose({
  loadReleases
})
</script>

<style scoped>
.dashboard-empty {
  text-align: center;
  padding: 3rem 1rem;
  color: #6c757d;
}

.empty-icon {
  font-size: 3rem;
  margin-bottom: 1rem;
  opacity: 0.3;
}

.releases-list {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.release-item {
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 1.5rem;
  background: #ffffff;
  transition: all 0.2s ease;
}

.release-item:hover {
  border-color: #d1d5db;
  box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
  transform: translateY(-2px);
}

.release-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 1rem;
}

.release-info {
  flex: 1;
}

.release-title {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.5rem;
  flex-wrap: wrap;
}

.release-name {
  font-size: 1.125rem;
  font-weight: 600;
  color: #1a202c;
  text-decoration: none;
}

.release-name:hover {
  color: #6366f1;
  text-decoration: underline;
}

.release-badges {
  display: flex;
  gap: 0.25rem;
  flex-wrap: wrap;
}

.release-description {
  color: #64748b;
  margin: 0;
  font-size: 0.95rem;
  line-height: 1.4;
}

.release-actions {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 0.75rem;
}

.action-buttons {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.crud-buttons {
  display: flex;
  gap: 0.25rem;
}

.release-summary {
  padding-top: 0.75rem;
  border-top: 1px solid #f1f5f9;
}

.artifacts-summary {
  font-size: 0.875rem;
  color: #64748b;
  display: flex;
  align-items: center;
}

.badge {
  font-size: 0.75rem;
  font-weight: 500;
}

.btn-sm {
  padding: 0.375rem 0.75rem;
  font-size: 0.875rem;
}

.view-all-notice {
  margin-top: 1.5rem;
  padding: 1rem;
  background: #f8f9fa;
  border: 1px solid #e9ecef;
  border-radius: 0.5rem;
  text-align: center;
}

.notice-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.75rem;
}

.notice-text {
  color: #64748b;
  font-size: 0.875rem;
}

.view-all-link {
  color: #6366f1;
  text-decoration: none;
  font-weight: 500;
  display: inline-flex;
  align-items: center;
  padding: 0.5rem 1rem;
  border: 1px solid #6366f1;
  border-radius: 0.375rem;
  transition: all 0.2s ease;
}

.view-all-link:hover {
  background: #6366f1;
  color: white;
  text-decoration: none;
}

@media (max-width: 768px) {
  .release-header {
    flex-direction: column;
    gap: 1rem;
  }

  .release-title {
    flex-direction: column;
    align-items: flex-start;
    gap: 0.5rem;
  }

  .release-actions {
    align-items: flex-start;
    flex-direction: row;
    justify-content: space-between;
    width: 100%;
  }

  .action-buttons {
    flex-direction: column;
    gap: 0.5rem;
    align-items: flex-end;
  }

  .crud-buttons {
    gap: 0.5rem;
  }
}
</style>