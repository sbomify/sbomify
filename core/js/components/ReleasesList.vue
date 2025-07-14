<template>
  <StandardCard
    title="All Releases"
    variant="default"
    shadow="sm"
  >
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
      <h5>No releases found</h5>
      <p class="mb-0 text-muted">Create your first product release to get started</p>
    </div>

    <!-- Releases Table -->
    <div v-else class="table-responsive">
      <table class="table dashboard-table">
        <thead>
          <tr>
            <th>Release Name</th>
            <th>Product</th>
            <th>Artifacts</th>
            <th>Created</th>
            <th class="text-center">Status</th>
            <th class="text-center">Actions</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="release in releases" :key="release.id">
            <td>
              <div class="release-info">
                <a
                  :href="getReleaseUrl(release)"
                  class="release-name"
                >
                  {{ release.name }}
                </a>
                <div v-if="release.is_latest || release.is_prerelease" class="release-badges">
                  <span v-if="release.is_latest" class="badge bg-success-subtle text-success">Latest</span>
                  <span v-if="release.is_prerelease" class="badge bg-warning-subtle text-warning">Pre-release</span>
                </div>
                <div v-if="release.description" class="release-description">
                  {{ release.description }}
                </div>
              </div>
            </td>
            <td>
              <a
                v-if="release.product"
                :href="getProductUrl(release)"
                class="product-link"
                :title="'View ' + release.product.name"
              >
                <i class="fas fa-box me-1"></i>
                {{ release.product.name }}
              </a>
              <span v-else class="text-muted">
                <i class="fas fa-box me-1"></i>
                Product not found
              </span>
            </td>
            <td>
              <div class="artifacts-info">
                <span class="artifact-count">
                  <i class="fas fa-puzzle-piece me-1"></i>
                  {{ release.artifacts_count || 0 }}
                </span>
                <div v-if="release.has_sboms" class="download-action">
                  <a
                    :href="getReleaseDownloadUrl(release)"
                    class="btn btn-sm btn-outline-primary"
                    title="Download release SBOM"
                  >
                    <i class="fas fa-download"></i>
                  </a>
                </div>
              </div>
            </td>
            <td>
              <span class="date-info" :title="formatDateFull(release.created_at)">
                {{ formatDate(release.created_at) }}
              </span>
            </td>
            <td class="text-center">
              <span
                v-if="release.is_public"
                class="badge bg-success-subtle text-success"
              >
                Public
              </span>
              <span
                v-else
                class="badge bg-secondary-subtle text-secondary"
              >
                Private
              </span>
            </td>
            <td class="text-center">
              <div class="action-buttons">
                <a
                  :href="getReleaseUrl(release)"
                  class="btn btn-sm btn-outline-primary"
                  title="View release details"
                >
                  <i class="fas fa-eye"></i>
                </a>
                <a
                  :href="getProductReleasesUrl(release)"
                  class="btn btn-sm btn-outline-secondary"
                  title="View all releases for this product"
                >
                  <i class="fas fa-list"></i>
                </a>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </StandardCard>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import $axios from '../utils'
import { showError } from '../alerts'
import { isAxiosError } from 'axios'
import StandardCard from './StandardCard.vue'

interface Product {
  id: string
  name: string
}

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
  product?: Product
}

// Component doesn't need props currently

// State
const releases = ref<Release[]>([])
const isLoading = ref(false)
const error = ref<string | null>(null)

// Computed
const hasData = computed(() => releases.value.length > 0)

// Methods
const formatDate = (dateString: string): string => {
  return new Date(dateString).toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric'
  })
}

const formatDateFull = (dateString: string): string => {
  return new Date(dateString).toLocaleString('en-US', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  })
}

const getReleaseUrl = (release: Release): string => {
  if (!release.product) {
    return '#'
  }
  return `/product/${release.product.id}/release/${release.id}/`
}

const getProductUrl = (release: Release): string => {
  if (!release.product) {
    return '#'
  }
  return `/product/${release.product.id}/`
}

const getProductReleasesUrl = (release: Release): string => {
  if (!release.product) {
    return '#'
  }
  return `/product/${release.product.id}/releases/`
}

const getReleaseDownloadUrl = (release: Release): string => {
  return `/api/v1/releases/${release.id}/download`
}

const loadReleases = async () => {
  isLoading.value = true
  error.value = null

  try {
    const response = await $axios.get('/api/v1/releases')
    const items = response.data.items || []

    // Normalize the response format to handle both old and new API structures
    const normalizedReleases = items.map((release: any) => {
      // Handle missing product object (stage environment)
      if (!release.product && release.product_id && release.product_name) {
        release.product = {
          id: release.product_id,
          name: release.product_name
        }
      }

      // Handle different field names
      if (release.artifact_count !== undefined && release.artifacts_count === undefined) {
        release.artifacts_count = release.artifact_count
      }

      // Handle missing has_sboms field
      if (release.has_sboms === undefined) {
        // If artifacts array exists, check if any are SBOMs
        if (Array.isArray(release.artifacts)) {
          release.has_sboms = release.artifacts.some((artifact: any) => artifact.artifact_type === 'sbom')
        } else {
          // Default to false if we can't determine
          release.has_sboms = false
        }
      }

      return release
    })

    // Filter out releases without products (as defensive coding)
    const validReleases = normalizedReleases.filter((release: Release) => {
      if (!release.product) {
        console.warn('Release without product found:', release)
        return false
      }
      return true
    })

    releases.value = validReleases.sort((a: Release, b: Release) => {
      return new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
    })
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

// Lifecycle
onMounted(async () => {
  await loadReleases()
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

.dashboard-table {
  margin-bottom: 0;
}

.dashboard-table th {
  border-top: none;
  font-weight: 600;
  color: #495057;
  background-color: #f8f9fa;
}

.dashboard-table td {
  vertical-align: middle;
}

.release-info {
  min-width: 200px;
}

.release-name {
  font-weight: 600;
  color: #1a202c;
  text-decoration: none;
  font-size: 1rem;
}

.release-name:hover {
  color: #6366f1;
  text-decoration: underline;
}

.release-badges {
  margin-top: 0.25rem;
}

.release-description {
  color: #64748b;
  font-size: 0.875rem;
  margin-top: 0.25rem;
  line-height: 1.4;
}

.product-link {
  color: #6366f1;
  text-decoration: none;
  font-weight: 500;
}

.product-link:hover {
  text-decoration: underline;
}

.artifacts-info {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.artifact-count {
  color: #64748b;
  font-size: 0.9rem;
}

.download-action {
  flex-shrink: 0;
}

.date-info {
  color: #64748b;
  font-size: 0.9rem;
}

.action-buttons {
  display: flex;
  gap: 0.5rem;
  justify-content: center;
}

.badge {
  font-size: 0.75rem;
  font-weight: 500;
}

.btn-sm {
  padding: 0.375rem 0.75rem;
  font-size: 0.875rem;
}

.table-responsive {
  border-radius: 0.375rem;
}

/* Ensure proper spacing for badges */
.badge + .badge {
  margin-left: 0.25rem;
}

@media (max-width: 992px) {
  .release-description {
    display: none;
  }

  .artifacts-info {
    flex-direction: column;
    align-items: flex-start;
    gap: 0.5rem;
  }
}

@media (max-width: 768px) {
  .dashboard-table th:nth-child(3),
  .dashboard-table td:nth-child(3),
  .dashboard-table th:nth-child(4),
  .dashboard-table td:nth-child(4) {
    display: none;
  }

  .action-buttons {
    flex-direction: column;
    gap: 0.25rem;
  }
}
</style>