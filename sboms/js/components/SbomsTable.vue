<template>
  <!-- Wrap in StandardCard only for non-public views -->
  <StandardCard
    v-if="!isPublicView"
    title="SBOMs"
    :collapsible="true"
    :defaultExpanded="true"
    storageKey="sboms-table"
  >
    <!-- Loading state -->
    <div v-if="isLoading" class="text-center py-4">
      <i class="fas fa-spinner fa-spin fa-2x text-primary"></i>
      <p class="mt-2 text-muted">Loading SBOMs...</p>
    </div>

    <!-- Error state -->
    <div v-else-if="error" class="alert alert-danger">
      {{ error }}
    </div>

    <!-- Empty state -->
    <div v-else-if="!hasData" class="text-center text-muted py-4">
      <i class="fas fa-file-alt fa-3x mb-3"></i>
      <p>No SBOMs found for this component.</p>
    </div>

    <!-- Data table -->
    <div v-else>
      <div class="data-table">
        <table class="table">
          <thead>
            <tr>
              <th scope="col">Name</th>
              <th scope="col">Artifact Type</th>
              <th scope="col">Format</th>
              <th scope="col">Version</th>
              <th scope="col">NTIA Compliant</th>
              <th scope="col">Created</th>
              <th scope="col">Releases</th>
              <th v-if="!isPublicView" scope="col">Vulnerabilities</th>
              <th scope="col">Actions</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="itemData in sbomsData" :key="itemData.sbom.id">
              <td>
                <a :href="getSbomDetailUrl(itemData.sbom.id)" title="Details" class="icon-link">
                  {{ itemData.sbom.name }}
                </a>
              </td>
              <td>SBOM</td>
              <td>
                <span class="badge bg-success-subtle text-success">
                  {{ getFormatDisplay(itemData.sbom.format) }} {{ itemData.sbom.format_version }}
                </span>
              </td>
              <td :title="itemData.sbom.version">
                {{ truncateText(itemData.sbom.version, 20) }}
              </td>
              <td>
                <NTIAComplianceBadge
                  :status="(itemData.sbom.ntia_compliance_status as 'compliant' | 'non_compliant' | 'unknown') || 'unknown'"
                  :complianceDetails="itemData.sbom.ntia_compliance_details || {}"
                />
              </td>
              <td>{{ formatDate(itemData.sbom.created_at) }}</td>
              <td>
                <div v-if="itemData.releases && itemData.releases.length > 0" class="release-tags">
                  <span
                    v-for="release in itemData.releases.slice(0, 2)"
                    :key="release.id"
                    class="badge bg-primary-subtle text-primary me-1 mb-1"
                    :title="`${release.product_name} - ${release.name}`"
                  >
                    {{ truncateText(release.name, 15) }}
                  </span>
                  <span
                    v-if="itemData.releases.length > 2"
                    class="badge bg-secondary-subtle text-secondary"
                    :title="`${itemData.releases.length - 2} more releases`"
                  >
                    +{{ itemData.releases.length - 2 }}
                  </span>
                </div>
                <span v-else class="text-muted">None</span>
              </td>
              <td v-if="!isPublicView">
                <a
                  :href="`/sbom/${itemData.sbom.id}/vulnerabilities`"
                  title="Vulnerabilities"
                  :class="['btn', 'btn-sm', 'btn-outline-warning', 'action-btn', { 'disabled': !itemData.has_vulnerabilities_report }]"
                >
                  <i class="fas fa-shield-alt me-1"></i> View
                </a>
              </td>
              <td>
                <div class="d-flex gap-2">
                  <a :href="getSbomDownloadUrl(itemData.sbom.id)" title="Download" class="btn btn-outline-primary btn-sm action-btn">
                    <i class="fas fa-download"></i>
                  </a>
                  <button
                    v-if="hasCrudPermissions"
                    class="btn btn-sm btn-outline-danger action-btn"
                    title="Delete SBOM"
                    :disabled="isDeleting === itemData.sbom.id"
                    @click="confirmDelete(itemData.sbom)"
                  >
                    <i v-if="isDeleting === itemData.sbom.id" class="fas fa-spinner fa-spin"></i>
                    <i v-else class="fas fa-trash"></i>
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Pagination Controls -->
      <PaginationControls
        v-if="paginationMeta && paginationMeta.total_pages > 1"
        v-model:current-page="currentPage"
        v-model:page-size="pageSize"
        :total-pages="paginationMeta.total_pages"
        :total-items="paginationMeta.total"
        :show-page-size-selector="true"
      />
    </div>
  </StandardCard>

  <div v-else>
    <!-- Public view without StandardCard wrapper -->
    <!-- Loading state -->
    <div v-if="isLoading" class="text-center py-4">
      <i class="fas fa-spinner fa-spin fa-2x text-primary"></i>
      <p class="mt-2 text-muted">Loading SBOMs...</p>
    </div>

    <!-- Error state -->
    <div v-else-if="error" class="alert alert-danger">
      {{ error }}
    </div>

    <!-- Empty state -->
    <div v-else-if="!hasData" class="text-center text-muted py-4">
      <i class="fas fa-file-alt fa-3x mb-3"></i>
      <p>No SBOMs found for this component.</p>
    </div>

    <!-- Data table -->
    <div v-else>
      <div class="data-table">
        <table class="table">
          <thead>
            <tr>
              <th scope="col">Name</th>
              <th scope="col">Artifact Type</th>
              <th scope="col">Format</th>
              <th scope="col">Version</th>
              <th scope="col">NTIA Compliant</th>
              <th scope="col">Created</th>
              <th scope="col">Releases</th>
              <th scope="col">Actions</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="itemData in sbomsData" :key="itemData.sbom.id">
              <td>
                <a :href="getSbomDetailUrl(itemData.sbom.id)" title="Details" class="icon-link">
                  {{ itemData.sbom.name }}
                </a>
              </td>
              <td>SBOM</td>
              <td>
                <span class="badge bg-success-subtle text-success">
                  {{ getFormatDisplay(itemData.sbom.format) }} {{ itemData.sbom.format_version }}
                </span>
              </td>
              <td :title="itemData.sbom.version">
                {{ truncateText(itemData.sbom.version, 20) }}
              </td>
              <td>
                <NTIAComplianceBadge
                  :status="(itemData.sbom.ntia_compliance_status as 'compliant' | 'non_compliant' | 'unknown') || 'unknown'"
                  :complianceDetails="itemData.sbom.ntia_compliance_details || {}"
                />
              </td>
              <td>{{ formatDate(itemData.sbom.created_at) }}</td>
              <td>
                <div v-if="itemData.releases && itemData.releases.length > 0" class="release-tags">
                  <span
                    v-for="release in itemData.releases.slice(0, 2)"
                    :key="release.id"
                    class="badge bg-primary-subtle text-primary me-1 mb-1"
                    :title="`${release.product_name} - ${release.name}`"
                  >
                    {{ truncateText(release.name, 15) }}
                  </span>
                  <span
                    v-if="itemData.releases.length > 2"
                    class="badge bg-secondary-subtle text-secondary"
                    :title="`${itemData.releases.length - 2} more releases`"
                  >
                    +{{ itemData.releases.length - 2 }}
                  </span>
                </div>
                <span v-else class="text-muted">None</span>
              </td>
              <td>
                <div class="d-flex gap-2">
                  <a :href="getSbomDownloadUrl(itemData.sbom.id)" title="Download" class="btn btn-outline-primary btn-sm action-btn">
                    <i class="fas fa-download"></i>
                  </a>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Pagination Controls -->
      <PaginationControls
        v-if="paginationMeta && paginationMeta.total_pages > 1"
        v-model:current-page="currentPage"
        v-model:page-size="pageSize"
        :total-pages="paginationMeta.total_pages"
        :total-items="paginationMeta.total"
        :show-page-size-selector="true"
      />
    </div>
  </div>

  <!-- Delete Confirmation Modal -->
  <DeleteConfirmationModal
    v-model:show="showDeleteModal"
    title="Delete SBOM"
    message="Are you sure you want to delete the SBOM"
    :item-name="sbomToDelete?.name"
    warning-message="This action cannot be undone and will permanently remove the SBOM from the system."
    confirm-text="Delete SBOM"
    :loading="!!isDeleting"
    @confirm="deleteSbom"
    @cancel="cancelDelete"
  />
</template>

<script setup lang="ts">
import { ref, onMounted, computed, watch } from 'vue'
import $axios from '../../../core/js/utils'
import { showSuccess, showError } from '../../../core/js/alerts'
import { isAxiosError } from 'axios'
import StandardCard from '../../../core/js/components/StandardCard.vue'
import DeleteConfirmationModal from '../../../core/js/components/DeleteConfirmationModal.vue'
import NTIAComplianceBadge from './NTIAComplianceBadge.vue'
import PaginationControls from '../../../core/js/components/PaginationControls.vue'

interface Sbom {
  id: string
  name: string
  format: string
  format_version: string
  version: string
  created_at: string
  ntia_compliance_status?: string
  ntia_compliance_details?: {
    errors?: Array<{
      field: string
      message: string
      suggestion: string
    }>
    checked_at?: string
    error_count?: number
  }
}

interface Release {
  id: string
  name: string
  product_name: string
  is_latest: boolean
  is_prerelease: boolean
  is_public: boolean
}

interface SbomData {
  sbom: Sbom
  has_vulnerabilities_report: boolean
  releases: Release[]
}

interface PaginationMeta {
  total: number
  page: number
  page_size: number
  total_pages: number
  has_previous: boolean
  has_next: boolean
}

interface PaginatedResponse {
  items: SbomData[]
  pagination: PaginationMeta
}

const props = defineProps<{
  sbomsDataElementId?: string
  componentId?: string
  hasCrudPermissions?: boolean | string
  isPublicView?: boolean
}>()

// State
const sbomsData = ref<SbomData[]>([])
const isLoading = ref(false)
const error = ref<string | null>(null)
const paginationMeta = ref<PaginationMeta | null>(null)
const currentPage = ref(1)
const pageSize = ref(15)
const showDeleteModal = ref(false)
const sbomToDelete = ref<Sbom | null>(null)
const isDeleting = ref<string | null>(null)

// Computed
const hasData = computed(() => sbomsData.value.length > 0)
const hasCrudPermissions = computed(() => {
  if (typeof props.hasCrudPermissions === 'string') {
    return props.hasCrudPermissions === 'true'
  }
  return props.hasCrudPermissions === true
})
const isPublicView = computed(() => props.isPublicView === true)

// Methods
const getSbomDetailUrl = (sbomId: string): string => {
  // For the new URL structure, we need the component ID
  if (props.componentId) {
    if (isPublicView.value) {
      return `/public/component/${props.componentId}/detailed/`
    }
    return `/component/${props.componentId}/detailed/`
  }

  // Fallback to old URLs if component ID not available
  if (isPublicView.value) {
    return `/public/sbom/${sbomId}/`
  }
  return `/sbom/${sbomId}/`
}

const getSbomDownloadUrl = (sbomId: string): string => {
  return `/api/v1/sboms/${sbomId}/download`
}

const getFormatDisplay = (format: string): string => {
  switch (format.toLowerCase()) {
    case 'cyclonedx':
      return 'CycloneDX'
    case 'spdx':
      return 'SPDX'
    default:
      return format.toUpperCase()
  }
}

const truncateText = (text: string | null | undefined, maxLength: number): string => {
  if (!text) return ''
  if (text.length <= maxLength) return text
  return text.substring(0, maxLength) + '...'
}

const formatDate = (dateString: string): string => {
  try {
    const date = new Date(dateString)
    return date.toLocaleDateString()
  } catch {
    return dateString
  }
}

const loadSboms = async () => {
  if (!props.componentId) {
    // Fallback to old behavior for backward compatibility
    return parseSbomsData()
  }

  isLoading.value = true
  error.value = null

  try {
    const params = new URLSearchParams({
      page: currentPage.value.toString(),
      page_size: pageSize.value.toString()
    })

    const response = await $axios.get(`/api/v1/components/${props.componentId}/sboms?${params}`)

    if (response.status < 200 || response.status >= 300) {
      throw new Error(`HTTP ${response.status}`)
    }

    const data = response.data as PaginatedResponse
    sbomsData.value = data.items
    paginationMeta.value = data.pagination
  } catch (err) {
    console.error('Error loading SBOMs:', err)
    error.value = 'Failed to load SBOMs'

    if (isAxiosError(err)) {
      showError(err.response?.data?.detail || 'Failed to load SBOMs')
    } else {
      showError('Failed to load SBOMs')
    }
  } finally {
    isLoading.value = false
  }
}

const parseSbomsData = (): void => {
  // Fallback method for backward compatibility with static JSON data
  try {
    if (props.sbomsDataElementId) {
      const element = document.getElementById(props.sbomsDataElementId)
      if (element && element.textContent) {
        const parsed = JSON.parse(element.textContent)
        if (Array.isArray(parsed)) {
          sbomsData.value = parsed
          return
        }
      }
    }

    sbomsData.value = []
  } catch (err) {
    console.error('Error parsing SBOMs data:', err)
    error.value = 'Failed to parse SBOMs data'
    sbomsData.value = []
  }
}

const confirmDelete = (sbom: Sbom) => {
  sbomToDelete.value = sbom
  showDeleteModal.value = true
}

const cancelDelete = () => {
  sbomToDelete.value = null
  showDeleteModal.value = false
}

const deleteSbom = async () => {
  if (!sbomToDelete.value) return

  const sbomId = sbomToDelete.value.id
  isDeleting.value = sbomId

  try {
    const response = await $axios.delete(`/api/v1/sboms/${sbomId}`)

    if (response.status === 204 || response.status === 200) {
      showSuccess('SBOM deleted successfully')
      // Reload data
      await loadSboms()
    } else {
      throw new Error(`HTTP ${response.status}`)
    }
  } catch (err) {
    console.error('Error deleting SBOM:', err)
    if (isAxiosError(err)) {
      showError(err.response?.data?.detail || 'Failed to delete SBOM')
    } else {
      showError('Failed to delete SBOM')
    }
  } finally {
    isDeleting.value = null
    cancelDelete()
  }
}

// Watchers for pagination changes
watch([currentPage, pageSize], () => {
  if (props.componentId) {
    loadSboms()
  }
})

// Lifecycle
onMounted(() => {
  loadSboms()
})
</script>

<style scoped>
.data-table {
  overflow-x: auto;
}

.table {
  margin-bottom: 0;
}

.icon-link {
  text-decoration: none;
}

.icon-link:hover {
  text-decoration: underline;
}

.btn.disabled {
  opacity: 0.6;
  pointer-events: none;
}

/* Action Button Styling */
.action-btn {
  border-radius: 0.5rem;
  font-weight: 500;
  transition: all 0.2s ease;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 2.5rem;
  height: 2.25rem;
  border-width: 1.5px;
  font-size: 0.875rem;
}

.action-btn i {
  font-size: 0.875rem;
}

.action-btn.btn-outline-primary {
  background-color: #fff;
  border-color: #0d6efd;
  color: #0d6efd;
  box-shadow: 0 1px 2px rgba(13, 110, 253, 0.15);
}

.action-btn.btn-outline-primary:hover {
  background: linear-gradient(135deg, #0d6efd, #0b5ed7);
  border-color: #0d6efd;
  color: white;
  transform: translateY(-1px);
  box-shadow: 0 2px 6px rgba(13, 110, 253, 0.3);
}

.action-btn.btn-outline-danger {
  background-color: #fff;
  border-color: #dc3545;
  color: #dc3545;
  box-shadow: 0 1px 2px rgba(220, 53, 69, 0.15);
}

.action-btn.btn-outline-danger:hover:not(:disabled) {
  background: linear-gradient(135deg, #dc3545, #c82333);
  border-color: #dc3545;
  color: white;
  transform: translateY(-1px);
  box-shadow: 0 2px 6px rgba(220, 53, 69, 0.3);
}

.action-btn.btn-outline-warning {
  background-color: #fff;
  border-color: #ffc107;
  color: #ffc107;
  box-shadow: 0 1px 2px rgba(255, 193, 7, 0.15);
}

.action-btn.btn-outline-warning:hover:not(:disabled) {
  background: linear-gradient(135deg, #ffc107, #e0a800);
  border-color: #ffc107;
  color: #000;
  transform: translateY(-1px);
  box-shadow: 0 2px 6px rgba(255, 193, 7, 0.3);
}

.action-btn:disabled {
  opacity: 0.6;
  pointer-events: none;
  transform: none;
}

/* Release Badges Styling */
.release-badges {
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem;
  align-items: center;
}

.release-badges .badge {
  font-size: 0.75rem;
  padding: 0.25rem 0.5rem;
  border-radius: 0.375rem;
  font-weight: 500;
  cursor: help;
  transition: all 0.2s ease;
}

.release-badges .badge:hover {
  transform: scale(1.05);
}

/* Responsive badge handling */
@media (max-width: 768px) {
  .release-badges {
    flex-direction: column;
    align-items: flex-start;
  }
}


</style>