<template>
    <StandardCard
    title="SBOMs"
    :collapsible="true"
    :defaultExpanded="true"
    storageKey="sboms-table"
  >
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
            <th scope="col">Vulnerabilities</th>
            <th scope="col">Actions</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="itemData in parsedSbomsData" :key="itemData.sbom.id">
            <td>
              <a :href="`/sbom/${itemData.sbom.id}`" title="Details" class="icon-link">
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
            <td>N/A</td>
            <td>{{ formatDate(itemData.sbom.created_at) }}</td>
            <td>
              <a
                :href="`/sbom/${itemData.sbom.id}/vulnerabilities`"
                title="Vulnerabilities"
                :class="['btn', 'btn-sm', 'btn-warning', { 'disabled': !itemData.has_vulnerabilities_report }]"
              >
                <i class="fas fa-shield-alt"></i> View
              </a>
            </td>
            <td>
              <div class="d-flex gap-1">
                <a :href="`/sbom/download/${itemData.sbom.id}`" title="Download" class="btn btn-sm btn-secondary">
                  <i class="fas fa-download"></i>
                </a>
                <button
                  v-if="hasCrudPermissions"
                  class="btn btn-sm btn-danger"
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
  </StandardCard>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import $axios from '../../../core/js/utils'
import { showSuccess, showError } from '../../../core/js/alerts'
import { isAxiosError } from 'axios'
import StandardCard from '../../../core/js/components/StandardCard.vue'
import DeleteConfirmationModal from '../../../core/js/components/DeleteConfirmationModal.vue'

interface Sbom {
  id: string
  name: string
  format: string
  format_version: string
  version: string
  created_at: string
}

interface SbomData {
  sbom: Sbom
  has_vulnerabilities_report: boolean
}

const props = defineProps<{
  sbomsDataElementId?: string
  componentId?: string
  hasCrudPermissions?: string
}>()

const parsedSbomsData = ref<SbomData[]>([])
const error = ref<string | null>(null)
const showDeleteModal = ref(false)
const sbomToDelete = ref<Sbom | null>(null)
const isDeleting = ref<string | null>(null)

const hasData = computed(() => parsedSbomsData.value.length > 0)
const hasCrudPermissions = computed(() => props.hasCrudPermissions === 'true')

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


</style>