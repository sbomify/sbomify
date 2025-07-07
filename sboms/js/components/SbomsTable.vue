<template>
  <!-- Wrap in StandardCard only for non-public views -->
  <StandardCard
    v-if="!isPublicView"
    title="SBOMs"
    :collapsible="true"
    :defaultExpanded="true"
    storageKey="sboms-table"
  >
    <!-- Table content -->
    <div v-if="error" class="alert alert-danger">
      {{ error }}
    </div>

    <div v-else-if="!hasData" class="text-center text-muted py-4">
      <i class="fas fa-file-alt fa-3x mb-3"></i>
      <p>No SBOMs found for this component.</p>
    </div>

    <div v-else class="data-table">
      <table class="table">
        <thead>
          <tr>
            <th scope="col">Name</th>
            <th scope="col">Artifact Type</th>
            <th scope="col">Format</th>
            <th scope="col">Version</th>
            <th scope="col">NTIA Compliant</th>
            <th scope="col">Created</th>
            <th v-if="!isPublicView" scope="col">Vulnerabilities</th>
            <th scope="col">Actions</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="itemData in parsedSbomsData" :key="itemData.sbom.id">
            <td>
              <a :href="getSbomDetailUrl(itemData.sbom.id)" title="Details" class="icon-link">
                {{ itemData.sbom.name }}
              </a>
            </td>
            <td>SBOM</td>
            <td>
              <span v-if="itemData.sbom.format === 'spdx'">SPDX</span>
              <span v-else-if="itemData.sbom.format === 'cyclonedx'">CycloneDX</span>
              <span v-else>{{ itemData.sbom.format }}</span>
              {{ itemData.sbom.format_version }}
            </td>
            <td :title="itemData.sbom.version">
              {{ truncateText(itemData.sbom.version, 20) }}
            </td>
            <td>
              <NTIAComplianceBadge
                :status="(itemData.sbom.ntia_compliance_status as 'compliant' | 'non_compliant' | 'unknown') || 'unknown'"
                :compliance-details="itemData.sbom.ntia_compliance_details || {}"
                :is-public-view="isPublicView"
              />
            </td>
            <td>{{ formatDate(itemData.sbom.created_at) }}</td>
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
  </StandardCard>

  <!-- For public views, render content directly (PublicPageLayout provides the card) -->
  <div v-else>
    <!-- Table content (same as above but without StandardCard wrapper) -->
    <div v-if="error" class="alert alert-danger">
      {{ error }}
    </div>

    <div v-else-if="!hasData" class="text-center text-muted py-4">
      <i class="fas fa-file-alt fa-3x mb-3"></i>
      <p>No SBOMs found for this component.</p>
    </div>

    <div v-else class="data-table">
      <table class="table">
        <thead>
          <tr>
            <th scope="col">Name</th>
            <th scope="col">Artifact Type</th>
            <th scope="col">Format</th>
            <th scope="col">Version</th>
            <th scope="col">NTIA Compliant</th>
            <th scope="col">Created</th>
            <th v-if="!isPublicView" scope="col">Vulnerabilities</th>
            <th scope="col">Actions</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="itemData in parsedSbomsData" :key="itemData.sbom.id">
            <td>
              <a :href="getSbomDetailUrl(itemData.sbom.id)" title="Details" class="icon-link">
                {{ itemData.sbom.name }}
              </a>
            </td>
            <td>SBOM</td>
            <td>
              <span v-if="itemData.sbom.format === 'spdx'">SPDX</span>
              <span v-else-if="itemData.sbom.format === 'cyclonedx'">CycloneDX</span>
              <span v-else>{{ itemData.sbom.format }}</span>
              {{ itemData.sbom.format_version }}
            </td>
            <td :title="itemData.sbom.version">
              {{ truncateText(itemData.sbom.version, 20) }}
            </td>
            <td>
              <NTIAComplianceBadge
                :status="(itemData.sbom.ntia_compliance_status as 'compliant' | 'non_compliant' | 'unknown') || 'unknown'"
                :compliance-details="itemData.sbom.ntia_compliance_details || {}"
                :is-public-view="isPublicView"
              />
            </td>
            <td>{{ formatDate(itemData.sbom.created_at) }}</td>
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
import { ref, onMounted, computed } from 'vue'
import $axios from '../../../core/js/utils'
import { showSuccess, showError } from '../../../core/js/alerts'
import { isAxiosError } from 'axios'
import StandardCard from '../../../core/js/components/StandardCard.vue'
import DeleteConfirmationModal from '../../../core/js/components/DeleteConfirmationModal.vue'
import NTIAComplianceBadge from './NTIAComplianceBadge.vue'

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

interface SbomData {
  sbom: Sbom
  has_vulnerabilities_report: boolean
}

const props = defineProps<{
  sbomsDataElementId?: string
  componentId?: string
  hasCrudPermissions?: boolean
  isPublicView?: boolean
}>()

const parsedSbomsData = ref<SbomData[]>([])
const error = ref<string | null>(null)
const showDeleteModal = ref(false)
const sbomToDelete = ref<Sbom | null>(null)
const isDeleting = ref<string | null>(null)

const hasData = computed(() => parsedSbomsData.value.length > 0)
const hasCrudPermissions = computed(() => props.hasCrudPermissions === true)
const isPublicView = computed(() => props.isPublicView === true)

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

const truncateText = (text: string, maxLength: number): string => {
  if (text.length <= maxLength) return text
  return text.substring(0, maxLength - 3) + '...'
}

const formatDate = (dateString: string): string => {
  try {
    const date = new Date(dateString)
    const formatted = date.toLocaleDateString()
    // Check if the date is invalid
    if (formatted === 'Invalid Date') {
      return dateString
    }
    return formatted
  } catch {
    return dateString
  }
}

const confirmDelete = (sbom: Sbom): void => {
  sbomToDelete.value = sbom
  showDeleteModal.value = true
}

const cancelDelete = (): void => {
  if (isDeleting.value) return // Prevent canceling during deletion
  showDeleteModal.value = false
  sbomToDelete.value = null
}

const deleteSbom = async (): Promise<void> => {
  if (!sbomToDelete.value) return

  isDeleting.value = sbomToDelete.value.id

  try {
    await $axios.delete(`/api/v1/sboms/sbom/${sbomToDelete.value.id}`)

    // Remove the deleted SBOM from the list
    parsedSbomsData.value = parsedSbomsData.value.filter(
      item => item.sbom.id !== sbomToDelete.value!.id
    )

    showSuccess(`SBOM "${sbomToDelete.value.name}" deleted successfully`)

    // Clear deleting state before closing modal
    isDeleting.value = null
    cancelDelete()
  } catch (err) {
    console.error('Error deleting SBOM:', err)
    let errorMessage = 'Failed to delete SBOM'

    if (isAxiosError(err)) {
      errorMessage = err.response?.data?.detail || errorMessage
    }

    showError(errorMessage)
    isDeleting.value = null
  }
}

const parseSbomsData = (): void => {
  try {
    if (props.sbomsDataElementId) {
      // Get data from JSON script element
      const element = document.getElementById(props.sbomsDataElementId)
      if (element && element.textContent) {
        const parsed = JSON.parse(element.textContent)
        if (Array.isArray(parsed)) {
          parsedSbomsData.value = parsed
          return
        }
      }
    }

    // If no valid data provided, show empty state
    parsedSbomsData.value = []
  } catch (err) {
    console.error('Error parsing SBOMs data:', err)
    error.value = 'Failed to parse SBOMs data'
    parsedSbomsData.value = []
  }
}

onMounted(() => {
  parseSbomsData()
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


</style>