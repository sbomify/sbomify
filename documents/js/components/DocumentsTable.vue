<template>
  <!-- Wrap in StandardCard only for non-public views -->
  <StandardCard
    v-if="!isPublicView"
    title="Documents"
    :collapsible="true"
    :defaultExpanded="true"
    storageKey="documents-table"
  >
    <!-- Loading state -->
    <div v-if="isLoading" class="text-center py-4">
      <i class="fas fa-spinner fa-spin fa-2x text-primary"></i>
      <p class="mt-2 text-muted">Loading documents...</p>
    </div>

    <!-- Error state -->
    <div v-else-if="error" class="alert alert-danger">
      {{ error }}
    </div>

    <!-- Empty state -->
    <div v-else-if="!hasData" class="text-center text-muted py-4">
      <i class="fas fa-file-alt fa-3x mb-3"></i>
      <p>No documents found for this component.</p>
    </div>

    <!-- Data table -->
    <div v-else>
      <div class="data-table">
        <table class="table">
          <thead>
            <tr>
              <th scope="col">Name</th>
              <th scope="col">Artifact Type</th>
              <th scope="col">Type</th>
              <th scope="col">Version</th>
              <th scope="col">Created</th>
              <th scope="col">Releases</th>
              <th scope="col">Actions</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in documentsData" :key="item.document.id">
              <td>
                <a :href="getDocumentDetailUrl(item.document.id)" title="Details" class="icon-link">
                  {{ item.document.name }}
                </a>
              </td>
              <td>Document</td>
              <td>
                <span class="badge bg-warning-subtle text-warning">{{ getDocumentTypeDisplay(item.document.document_type) }}</span>
              </td>
              <td :title="item.document.version">
                {{ truncateText(item.document.version, 20) }}
              </td>
              <td>{{ formatDate(item.document.created_at) }}</td>
              <td>
                <div v-if="item.releases && item.releases.length > 0" class="release-tags">
                  <span
                    v-for="release in item.releases.slice(0, 2)"
                    :key="release.id"
                    class="badge bg-primary-subtle text-primary me-1 mb-1"
                    :title="`${release.product_name} - ${release.name}`"
                  >
                    {{ truncateText(release.name, 15) }}
                  </span>
                  <span
                    v-if="item.releases.length > 2"
                    class="badge bg-secondary-subtle text-secondary"
                    :title="`${item.releases.length - 2} more releases`"
                  >
                    +{{ item.releases.length - 2 }}
                  </span>
                </div>
                <span v-else class="text-muted">None</span>
              </td>
              <td>
                <div class="d-flex gap-2">
                  <a :href="getDocumentDownloadUrl(item.document.id)" title="Download" class="btn btn-outline-primary btn-sm action-btn">
                    <i class="fas fa-download"></i>
                  </a>
                  <button
                    v-if="hasCrudPermissions"
                    class="btn btn-sm btn-outline-danger action-btn"
                    title="Delete Document"
                    :disabled="isDeleting === item.document.id"
                    @click="confirmDelete(item.document)"
                  >
                    <i v-if="isDeleting === item.document.id" class="fas fa-spinner fa-spin"></i>
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
      <p class="mt-2 text-muted">Loading documents...</p>
    </div>

    <!-- Error state -->
    <div v-else-if="error" class="alert alert-danger">
      {{ error }}
    </div>

    <!-- Empty state -->
    <div v-else-if="!hasData" class="text-center text-muted py-4">
      <i class="fas fa-file-alt fa-3x mb-3"></i>
      <p>No documents found for this component.</p>
    </div>

    <!-- Data table -->
    <div v-else>
      <div class="data-table">
        <table class="table">
          <thead>
            <tr>
              <th scope="col">Name</th>
              <th scope="col">Artifact Type</th>
              <th scope="col">Type</th>
              <th scope="col">Version</th>
              <th scope="col">Created</th>
              <th scope="col">Releases</th>
              <th scope="col">Actions</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in documentsData" :key="item.document.id">
              <td>
                <a :href="getDocumentDetailUrl(item.document.id)" title="Details" class="icon-link">
                  {{ item.document.name }}
                </a>
              </td>
              <td>Document</td>
              <td>
                <span class="badge bg-warning-subtle text-warning">{{ getDocumentTypeDisplay(item.document.document_type) }}</span>
              </td>
              <td :title="item.document.version">
                {{ truncateText(item.document.version, 20) }}
              </td>
              <td>{{ formatDate(item.document.created_at) }}</td>
              <td>
                <div v-if="item.releases && item.releases.length > 0" class="release-tags">
                  <span
                    v-for="release in item.releases.slice(0, 2)"
                    :key="release.id"
                    class="badge bg-primary-subtle text-primary me-1 mb-1"
                    :title="`${release.product_name} - ${release.name}`"
                  >
                    {{ truncateText(release.name, 15) }}
                  </span>
                  <span
                    v-if="item.releases.length > 2"
                    class="badge bg-secondary-subtle text-secondary"
                    :title="`${item.releases.length - 2} more releases`"
                  >
                    +{{ item.releases.length - 2 }}
                  </span>
                </div>
                <span v-else class="text-muted">None</span>
              </td>
              <td>
                <div class="d-flex gap-2">
                  <a :href="getDocumentDownloadUrl(item.document.id)" title="Download" class="btn btn-outline-primary btn-sm action-btn">
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
    title="Delete Document"
    message="Are you sure you want to delete the document"
    :item-name="documentToDelete?.name"
    warning-message="This action cannot be undone and will permanently remove the document from the system."
    confirm-text="Delete Document"
    :loading="!!isDeleting"
    @confirm="deleteDocument"
    @cancel="cancelDelete"
  />
</template>

<script setup lang="ts">
import { ref, onMounted, computed, watch } from 'vue'
import $axios from '../../../core/js/utils'
import { showSuccess, showError } from '../../../core/js/alerts'
import { isAxiosError } from 'axios'
import DeleteConfirmationModal from '../../../core/js/components/DeleteConfirmationModal.vue'
import StandardCard from '../../../core/js/components/StandardCard.vue'
import PaginationControls from '../../../core/js/components/PaginationControls.vue'

interface Document {
  id: string
  name: string
  document_type: string
  version: string
  content_type: string
  file_size: number | null
  created_at: string
  description?: string
}

interface Release {
  id: string
  name: string
  product_name: string
  is_latest: boolean
  is_prerelease: boolean
  is_public: boolean
}

interface DocumentData {
  document: Document
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
  items: DocumentData[]
  pagination: PaginationMeta
}

const props = defineProps<{
  documentsDataElementId?: string
  componentId?: string
  hasCrudPermissions?: boolean | string
  isPublicView?: boolean
}>()

// State
const documentsData = ref<DocumentData[]>([])
const isLoading = ref(false)
const error = ref<string | null>(null)
const paginationMeta = ref<PaginationMeta | null>(null)
const currentPage = ref(1)
const pageSize = ref(15)
const showDeleteModal = ref(false)
const documentToDelete = ref<Document | null>(null)
const isDeleting = ref<string | null>(null)

// Computed
const hasData = computed(() => documentsData.value.length > 0)
const hasCrudPermissions = computed(() => {
  if (typeof props.hasCrudPermissions === 'string') {
    return props.hasCrudPermissions === 'true'
  }
  return props.hasCrudPermissions || false
})
const isPublicView = computed(() => props.isPublicView === true)

// Methods
const getDocumentDetailUrl = (documentId: string): string => {
  // For the new URL structure, we need the component ID
  if (props.componentId) {
    if (isPublicView.value) {
      return `/public/component/${props.componentId}/detailed/`
    }
    return `/component/${props.componentId}/detailed/`
  }

  // Fallback to document URLs if component ID not available
  if (isPublicView.value) {
    return `/public/document/${documentId}/`
  }
  return `/document/${documentId}/`
}

const getDocumentDownloadUrl = (documentId: string): string => {
  return `/api/v1/documents/${documentId}/download`
}

const getDocumentTypeDisplay = (documentType: string): string => {
  if (!documentType) return 'Document'

  // Convert snake_case to Title Case
  return documentType
    .split('_')
    .map(word => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ')
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

const loadDocuments = async () => {
  if (!props.componentId) {
    // Fallback to old behavior for backward compatibility
    return parseDocumentsData()
  }

  isLoading.value = true
  error.value = null

  try {
    const params = new URLSearchParams({
      page: currentPage.value.toString(),
      page_size: pageSize.value.toString()
    })

    const response = await $axios.get(`/api/v1/components/${props.componentId}/documents?${params}`)

    if (response.status < 200 || response.status >= 300) {
      throw new Error(`HTTP ${response.status}`)
    }

    const data = response.data as PaginatedResponse
    documentsData.value = data.items
    paginationMeta.value = data.pagination
  } catch (err) {
    console.error('Error loading documents:', err)
    error.value = 'Failed to load documents'

    if (isAxiosError(err)) {
      showError(err.response?.data?.detail || 'Failed to load documents')
    } else {
      showError('Failed to load documents')
    }
  } finally {
    isLoading.value = false
  }
}

const parseDocumentsData = (): void => {
  // Fallback method for backward compatibility with static JSON data
  try {
    if (props.documentsDataElementId) {
      const element = document.getElementById(props.documentsDataElementId)
      if (element && element.textContent) {
        const parsed = JSON.parse(element.textContent)
        if (Array.isArray(parsed)) {
          documentsData.value = parsed
          return
        }
      }
    }

    documentsData.value = []
  } catch (err) {
    console.error('Error parsing documents data:', err)
    error.value = 'Failed to parse documents data'
    documentsData.value = []
  }
}

const confirmDelete = (document: Document) => {
  documentToDelete.value = document
  showDeleteModal.value = true
}

const cancelDelete = () => {
  documentToDelete.value = null
  showDeleteModal.value = false
}

const deleteDocument = async () => {
  if (!documentToDelete.value) return

  const documentId = documentToDelete.value.id
  isDeleting.value = documentId

  try {
    const response = await $axios.delete(`/api/v1/documents/${documentId}`)

    if (response.status === 204 || response.status === 200) {
      showSuccess('Document deleted successfully')
      // Reload data
      await loadDocuments()
    } else {
      throw new Error(`HTTP ${response.status}`)
    }
  } catch (err) {
    console.error('Error deleting document:', err)
    if (isAxiosError(err)) {
      showError(err.response?.data?.detail || 'Failed to delete document')
    } else {
      showError('Failed to delete document')
    }
  } finally {
    isDeleting.value = null
    cancelDelete()
  }
}

// Watchers for pagination changes
watch([currentPage, pageSize], () => {
  if (props.componentId) {
    loadDocuments()
  }
})

// Lifecycle
onMounted(() => {
  loadDocuments()
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

.modal {
  display: block;
}

.modal-backdrop {
  position: fixed;
  top: 0;
  left: 0;
  z-index: 1040;
  width: 100vw;
  height: 100vh;
  background-color: #000;
  opacity: 0.5;
}

.version-display {
  display: inline-block;
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: bottom;
}

/* Release badges styling */
.release-badges {
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem;
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

.action-btn.btn-outline-danger:hover {
  background: linear-gradient(135deg, #dc3545, #c82333);
  border-color: #dc3545;
  color: white;
  transform: translateY(-1px);
  box-shadow: 0 2px 6px rgba(220, 53, 69, 0.3);
}
</style>