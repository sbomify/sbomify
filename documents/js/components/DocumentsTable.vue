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
        <table class="table dashboard-table">
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
              <td data-label="Name">
                <a :href="getDocumentDetailUrl(item.document.id)" title="Details" class="icon-link">
                  {{ item.document.name }}
                </a>
              </td>
              <td data-label="Artifact Type">Document</td>
              <td data-label="Type">
                <span class="badge bg-warning-subtle text-warning">{{ getDocumentTypeDisplay(item.document.document_type) }}</span>
              </td>
              <td data-label="Version" :title="item.document.version">
                {{ utils.truncateText(item.document.version, 20) }}
              </td>
              <td data-label="Created">{{ utils.formatDate(item.document.created_at) }}</td>
              <td data-label="Releases">
                <ReleaseList
                  :releases="item.releases"
                  :item-id="item.document.id"
                  :is-public-view="isPublicView"
                  :view-all-url="getDocumentReleasesUrl(item.document.id)"
                />
              </td>
              <td data-label="Actions">
                <div class="d-flex gap-2">
                  <a :href="getDocumentDownloadUrl(item.document.id)" title="Download" class="btn btn-outline-primary btn-sm action-btn">
                    <i class="fas fa-download"></i>
                  </a>
                  <button
                    v-if="hasCrudPermissions"
                    class="btn btn-sm btn-outline-secondary action-btn"
                    title="Edit Document"
                    @click="editDocument(item.document)"
                  >
                    <i class="fas fa-edit"></i>
                  </button>
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
                {{ utils.truncateText(item.document.version, 20) }}
              </td>
              <td>{{ utils.formatDate(item.document.created_at) }}</td>
              <td>
                <ReleaseList
                  :releases="item.releases"
                  :item-id="item.document.id"
                  :is-public-view="isPublicView"
                  :view-all-url="getDocumentReleasesUrl(item.document.id)"
                />
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

  <!-- Edit Document Modal -->
  <div v-if="showEditModal" class="modal fade show d-block" tabindex="-1" style="z-index: var(--z-index-modal);">
    <div class="modal-dialog modal-lg">
      <div class="modal-content">
        <div class="modal-header">
          <h5 class="modal-title">Edit Document</h5>
          <button type="button" class="btn-close" aria-label="Close" @click="cancelEdit"></button>
        </div>
        <div class="modal-body">
          <form @submit.prevent="updateDocument">
            <div class="row">
              <div class="col-md-6">
                <div class="mb-3">
                  <label for="editDocumentName" class="form-label">Name <span class="text-danger">*</span></label>
                  <input
                    id="editDocumentName"
                    v-model="editForm.name"
                    type="text"
                    class="form-control"
                    required
                    placeholder="Enter document name"
                  />
                </div>
              </div>
              <div class="col-md-6">
                <div class="mb-3">
                  <label for="editDocumentVersion" class="form-label">Version <span class="text-danger">*</span></label>
                  <input
                    id="editDocumentVersion"
                    v-model="editForm.version"
                    type="text"
                    class="form-control"
                    required
                    placeholder="Enter version (e.g., 1.0)"
                  />
                </div>
              </div>
            </div>
            <div class="mb-3">
              <label for="editDocumentType" class="form-label">Document Type</label>
              <select
                id="editDocumentType"
                v-model="editForm.document_type"
                class="form-select"
              >
                <option value="">Select document type</option>
                <option value="specification">Specification</option>
                <option value="manual">Manual</option>
                <option value="readme">README</option>
                <option value="documentation">Documentation</option>
                <option value="build-instructions">Build Instructions</option>
                <option value="configuration">Configuration</option>
                <option value="license">License</option>
                <option value="compliance">Compliance</option>
                <option value="evidence">Evidence</option>
                <option value="changelog">Changelog</option>
                <option value="release-notes">Release Notes</option>
                <option value="security-advisory">Security Advisory</option>
                <option value="vulnerability-report">Vulnerability Report</option>
                <option value="threat-model">Threat Model</option>
                <option value="risk-assessment">Risk Assessment</option>
                <option value="pentest-report">Penetration Test Report</option>
                <option value="static-analysis">Static Analysis Report</option>
                <option value="dynamic-analysis">Dynamic Analysis Report</option>
                <option value="quality-metrics">Quality Metrics</option>
                <option value="maturity-report">Maturity Report</option>
                <option value="report">Report</option>
                <option value="other">Other</option>
              </select>
            </div>
            <div class="mb-3">
              <label for="editDocumentDescription" class="form-label">Description</label>
              <textarea
                id="editDocumentDescription"
                v-model="editForm.description"
                class="form-control"
                rows="3"
                placeholder="Enter description (optional)"
              ></textarea>
            </div>
          </form>
        </div>
        <div class="modal-footer">
          <button type="button" class="btn btn-secondary" @click="cancelEdit">Cancel</button>
          <button
            type="button"
            class="btn btn-primary"
            :disabled="isUpdating || !editForm.name || !editForm.version"
            @click="updateDocument"
          >
            <span v-if="isUpdating" class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>
            Update Document
          </button>
        </div>
      </div>
    </div>
  </div>

  <!-- Modal Backdrop -->
  <div v-if="showEditModal" class="modal-backdrop fade show" style="z-index: var(--z-index-modal-backdrop);" @click="cancelEdit"></div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed, watch } from 'vue'
import $axios from '../../../core/js/utils'
import { showSuccess, showError } from '../../../core/js/alerts'
import { isAxiosError } from 'axios'
import DeleteConfirmationModal from '../../../core/js/components/DeleteConfirmationModal.vue'
import StandardCard from '../../../core/js/components/StandardCard.vue'
import PaginationControls from '../../../core/js/components/PaginationControls.vue'
import ReleaseList from '../../../core/js/components/ReleaseList.vue'
import { useCommonUtils } from '../../../core/js/composables/useCommonUtils'
import { useUrlGeneration } from '../../../core/js/composables/useUrlGeneration'
import { PAGINATION } from '../../../core/js/constants'

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
  product_id?: string // Added for new URL structure
  product?: { // Added for new URL structure
    id: string
    name: string
  }
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

// Use composables
const utils = useCommonUtils()

// State
const documentsData = ref<DocumentData[]>([])
const isLoading = ref(false)
const error = ref<string | null>(null)
const paginationMeta = ref<PaginationMeta | null>(null)
const currentPage = ref(1)
const pageSize = ref(PAGINATION.DEFAULT_PAGE_SIZE)
const showDeleteModal = ref(false)
const documentToDelete = ref<Document | null>(null)
const isDeleting = ref<string | null>(null)
const showEditModal = ref(false)
const documentToEdit = ref<Document | null>(null)
const isUpdating = ref(false)
const editForm = ref({
  name: '',
  version: '',
  document_type: '',
  description: ''
})

// Computed
const hasData = computed(() => documentsData.value.length > 0)
const hasCrudPermissions = computed(() => {
  if (typeof props.hasCrudPermissions === 'string') {
    return props.hasCrudPermissions === 'true'
  }
  return props.hasCrudPermissions || false
})
const isPublicView = computed(() => props.isPublicView === true)

// URL generation composable (needs to be after isPublicView is defined)
const urlGen = useUrlGeneration(isPublicView.value)

// Methods - using URL generation composable
const getDocumentDetailUrl = (documentId: string): string => {
  return urlGen.getDocumentDetailUrl(documentId, props.componentId)
}

const getDocumentDownloadUrl = (documentId: string): string => {
  return urlGen.getDocumentDownloadUrl(documentId)
}

const getDocumentReleasesUrl = (documentId: string): string => {
  return urlGen.getDocumentReleasesUrl(documentId)
}





const getDocumentTypeDisplay = (documentType: string): string => {
  if (!documentType) return 'Document'

  // Map document types to display names
  const typeDisplayMap: { [key: string]: string } = {
    // Technical Documentation
    'specification': 'Specification',
    'manual': 'Manual',
    'readme': 'README',
    'documentation': 'Documentation',
    'build-instructions': 'Build Instructions',
    'configuration': 'Configuration',

    // Legal and Compliance
    'license': 'License',
    'compliance': 'Compliance',
    'evidence': 'Evidence',

    // Release Information
    'changelog': 'Changelog',
    'release-notes': 'Release Notes',

    // Security Documents
    'security-advisory': 'Security Advisory',
    'vulnerability-report': 'Vulnerability Report',
    'threat-model': 'Threat Model',
    'risk-assessment': 'Risk Assessment',
    'pentest-report': 'Penetration Test Report',

    // Analysis Reports
    'static-analysis': 'Static Analysis Report',
    'dynamic-analysis': 'Dynamic Analysis Report',
    'quality-metrics': 'Quality Metrics',
    'maturity-report': 'Maturity Report',
    'report': 'Report',

    // Other
    'other': 'Other'
  }

  return typeDisplayMap[documentType] || documentType
    .split('-')
    .map(word => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ')
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

const editDocument = (document: Document) => {
  documentToEdit.value = document
  editForm.value = {
    name: document.name,
    version: document.version,
    document_type: document.document_type,
    description: document.description || ''
  }
  showEditModal.value = true
}

const cancelEdit = () => {
  documentToEdit.value = null
  showEditModal.value = false
  editForm.value = {
    name: '',
    version: '',
    document_type: '',
    description: ''
  }
}

const updateDocument = async () => {
  if (!documentToEdit.value) return

  isUpdating.value = true

  try {
    const response = await $axios.patch(`/api/v1/documents/${documentToEdit.value.id}`, editForm.value)

    if (response.status === 200) {
      showSuccess('Document updated successfully')
      // Reload data
      await loadDocuments()
    } else {
      throw new Error(`HTTP ${response.status}`)
    }
  } catch (err) {
    console.error('Error updating document:', err)
    if (isAxiosError(err)) {
      showError(err.response?.data?.detail || 'Failed to update document')
    } else {
      showError('Failed to update document')
    }
  } finally {
    isUpdating.value = false
    cancelEdit()
  }
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

.action-btn.btn-outline-secondary {
  background-color: #fff;
  border-color: #6c757d;
  color: #6c757d;
  box-shadow: 0 1px 2px rgba(108, 117, 125, 0.15);
}

.action-btn.btn-outline-secondary:hover {
  background: linear-gradient(135deg, #6c757d, #5a6268);
  border-color: #6c757d;
  color: white;
  transform: translateY(-1px);
  box-shadow: 0 2px 6px rgba(108, 117, 125, 0.3);
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

/* Edit Modal Styling */
.modal {
  z-index: 1055;
}

.modal-backdrop {
  z-index: 1050;
}

.modal-content {
  border-radius: 0.5rem;
  box-shadow: 0 0.5rem 1rem rgba(0, 0, 0, 0.15);
}

.modal-header {
  border-bottom: 1px solid #dee2e6;
  padding: 1rem 1.5rem;
}

.modal-body {
  padding: 1.5rem;
}

.modal-footer {
  border-top: 1px solid #dee2e6;
  padding: 1rem 1.5rem;
}

.form-label {
  font-weight: 500;
  color: #495057;
  margin-bottom: 0.5rem;
}

.form-control,
.form-select {
  border-radius: 0.375rem;
  border: 1px solid #ced4da;
  padding: 0.5rem 0.75rem;
  font-size: 1rem;
  transition: border-color 0.15s ease-in-out, box-shadow 0.15s ease-in-out;
}

.form-control:focus,
.form-select:focus {
  border-color: #86b7fe;
  outline: 0;
  box-shadow: 0 0 0 0.25rem rgba(13, 110, 253, 0.25);
}

.btn-close {
  padding: 0.5rem 0.5rem;
  margin: -0.5rem -0.5rem -0.5rem auto;
}
</style>