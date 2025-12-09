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
      <SbomsDataTable
        :sboms-data="sbomsData"
        :component-id="componentId"
        :is-public-view="isPublicView"
        :show-vulnerabilities="!isPublicView"
        :show-delete-button="hasCrudPermissions"
        :is-deleting="isDeleting"
        :team-billing-plan="teamBillingPlan"
        :team-key="teamKey"
        @delete="confirmDelete"
        @scan-completed="handleScanCompleted"
      />

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
      <SbomsDataTable
        :sboms-data="sbomsData"
        :component-id="componentId"
        :is-public-view="isPublicView"
        :show-vulnerabilities="false"
        :show-delete-button="false"
        :is-deleting="null"
        :team-billing-plan="teamBillingPlan"
        :team-key="teamKey"
        @delete="confirmDelete"
        @scan-completed="handleScanCompleted"
      />

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
import PaginationControls from '../../../core/js/components/PaginationControls.vue'
import SbomsDataTable from './SbomsDataTable.vue'

type NtiaStatus = 'compliant' | 'partial' | 'non_compliant' | 'unknown'

interface NtiaComplianceError {
  field: string
  message: string
  suggestion?: string
}

interface NtiaComplianceCheck {
  element?: string
  title: string
  status?: string
  message: string
  suggestion?: string | null
  affected?: string[]
}

interface NtiaComplianceSection {
  name?: string
  title: string
  summary: string
  status?: string
  metrics?: {
    total?: number
    pass?: number
    warning?: number
    fail?: number
    unknown?: number
  }
  checks?: NtiaComplianceCheck[]
}

interface NtiaComplianceSummary {
  errors?: number
  warnings?: number
  status?: string
  score?: number | null
  checks?: {
    total?: number
    pass?: number
    warning?: number
    fail?: number
    unknown?: number
  }
  sections?: Record<
    string,
    {
      status?: string
      metrics?: {
        total?: number
        pass?: number
        warning?: number
        fail?: number
        unknown?: number
      }
      title?: string
      summary?: string
    }
  >
}

interface NtiaComplianceDetails {
  is_compliant?: boolean
  status?: string
  error_count?: number
  warning_count?: number
  errors?: NtiaComplianceError[]
  warnings?: NtiaComplianceCheck[]
  sections?: NtiaComplianceSection[]
  summary?: NtiaComplianceSummary
  checked_at?: string | null
  format?: string
}

interface Sbom {
  id: string
  name: string
  format: string
  format_version: string
  version: string
  created_at: string
  ntia_compliance_status?: NtiaStatus
  ntia_compliance_details?: NtiaComplianceDetails | null
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
  teamBillingPlan?: string
  teamKey?: string
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
    const response = await $axios.delete(`/api/v1/sboms/sbom/${sbomId}`)

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

const handleScanCompleted = async (sbomId: string) => {
  console.log(`Scan completed for SBOM ${sbomId}, refreshing data...`)
  // Refresh the data to update the has_vulnerabilities_report flag
  await loadSboms()
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
/* SbomsTable component styles */
</style>
