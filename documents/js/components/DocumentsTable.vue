<template>
  <StandardCard
    title="Documents"
    :collapsible="true"
    :defaultExpanded="true"
    storageKey="documents-table"
  >
    <div v-if="error" class="alert alert-danger">
      {{ error }}
    </div>

    <div v-else-if="!hasData" class="text-center text-muted py-4">
      <i class="fas fa-file-alt fa-3x mb-3"></i>
      <p>No documents found for this component.</p>
    </div>

    <div v-else class="data-table">
      <table class="table">
        <thead>
          <tr>
            <th scope="col">Name</th>
            <th scope="col">Type</th>
            <th scope="col">Version</th>
            <th scope="col">Content Type</th>
            <th scope="col">Size</th>
            <th scope="col">Created</th>
            <th scope="col">Actions</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="itemData in parsedDocumentsData" :key="itemData.document.id">
            <td>
              <a :href="`/document/${itemData.document.id}`" title="Details" class="icon-link">
                {{ itemData.document.name }}
              </a>
            </td>
            <td>
              <span v-if="itemData.document.document_type" class="badge bg-info">
                {{ itemData.document.document_type }}
              </span>
              <span v-else class="text-muted">Document</span>
            </td>
            <td :title="itemData.document.version">
              {{ truncateText(itemData.document.version, 20) || 'N/A' }}
            </td>
            <td>
              <small class="text-muted">{{ itemData.document.content_type || 'Unknown' }}</small>
            </td>
            <td>
              <small class="text-muted">{{ formatFileSize(itemData.document.file_size) }}</small>
            </td>
            <td>{{ formatDate(itemData.document.created_at) }}</td>
            <td>
              <div class="d-flex gap-1">
                <a :href="`/document/download/${itemData.document.id}`" title="Download" class="btn btn-sm btn-secondary">
                  <i class="fas fa-download"></i>
                </a>
                <button
                  v-if="hasCrudPermissions"
                  class="btn btn-sm btn-primary"
                  title="Edit Metadata"
                  @click="openEditModal(itemData.document)"
                >
                  <i class="fas fa-edit"></i>
                </button>
                <button
                  v-if="hasCrudPermissions"
                  class="btn btn-sm btn-danger"
                  title="Delete Document"
                  :disabled="isDeleting === itemData.document.id"
                  @click="confirmDelete(itemData.document)"
                >
                  <i v-if="isDeleting === itemData.document.id" class="fas fa-spinner fa-spin"></i>
                  <i v-else class="fas fa-trash"></i>
                </button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Edit Document Modal -->
    <div v-if="showEditModal" class="modal fade show d-block" tabindex="-1" style="background-color: rgba(0,0,0,0.5)">
      <div class="modal-dialog">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title">Edit Document Metadata</h5>
            <button type="button" class="btn-close" @click="cancelEdit" :disabled="isUpdating"></button>
          </div>
          <div class="modal-body">
            <form @submit.prevent="updateDocument">
              <div class="mb-3">
                <label for="edit-name" class="form-label">Name <span class="text-danger">*</span></label>
                <input
                  id="edit-name"
                  v-model="editForm.name"
                  type="text"
                  class="form-control"
                  required
                >
              </div>

              <div class="mb-3">
                <label for="edit-version" class="form-label">Version <span class="text-danger">*</span></label>
                <input
                  id="edit-version"
                  v-model="editForm.version"
                  type="text"
                  class="form-control"
                  required
                >
              </div>

              <div class="mb-3">
                <label for="edit-type" class="form-label">Document Type</label>
                <select id="edit-type" v-model="editForm.document_type" class="form-select">
                  <option value="">Select document type (optional)</option>
                  <option value="specification">Specification</option>
                  <option value="manual">Manual</option>
                  <option value="report">Report</option>
                  <option value="license">License</option>
                  <option value="readme">README</option>
                  <option value="changelog">Changelog</option>
                  <option value="documentation">Documentation</option>
                  <option value="compliance">Compliance</option>
                  <option value="other">Other</option>
                </select>
              </div>

              <div class="mb-3">
                <label for="edit-description" class="form-label">Description</label>
                <textarea
                  id="edit-description"
                  v-model="editForm.description"
                  class="form-control"
                  rows="3"
                  placeholder="Brief description of this document (optional)"
                ></textarea>
              </div>

              <div class="text-muted small mb-3">
                <i class="fas fa-info-circle"></i>
                Note: Only metadata can be edited. To change the document file, upload a new document.
              </div>
            </form>
          </div>
          <div class="modal-footer">
            <button type="button" class="btn btn-secondary" @click="cancelEdit" :disabled="isUpdating">
              Cancel
            </button>
            <button type="button" class="btn btn-primary" @click="updateDocument" :disabled="isUpdating || !isFormValid">
              <i v-if="isUpdating" class="fas fa-spinner fa-spin me-1"></i>
              Update Metadata
            </button>
          </div>
        </div>
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
  </StandardCard>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import $axios from '../../../core/js/utils'
import { showSuccess, showError } from '../../../core/js/alerts'
import { isAxiosError } from 'axios'
import StandardCard from '../../../core/js/components/StandardCard.vue'
import DeleteConfirmationModal from '../../../core/js/components/DeleteConfirmationModal.vue'

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

interface DocumentData {
  document: Document
}

interface EditForm {
  name: string
  version: string
  document_type: string
  description: string
}

const props = defineProps<{
  documentsDataElementId?: string
  componentId?: string
  hasCrudPermissions?: string
}>()

const parsedDocumentsData = ref<DocumentData[]>([])
const error = ref<string | null>(null)
const showDeleteModal = ref(false)
const showEditModal = ref(false)
const documentToDelete = ref<Document | null>(null)
const documentToEdit = ref<Document | null>(null)
const isDeleting = ref<string | null>(null)
const isUpdating = ref(false)
const editForm = ref<EditForm>({
  name: '',
  version: '',
  document_type: '',
  description: ''
})

const hasData = computed(() => parsedDocumentsData.value.length > 0)
const hasCrudPermissions = computed(() => props.hasCrudPermissions === 'true')
const isFormValid = computed(() => editForm.value.name.trim() && editForm.value.version.trim())

const truncateText = (text: string, maxLength: number): string => {
  if (!text || text.length <= maxLength) return text
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

const formatFileSize = (bytes: number | null): string => {
  if (!bytes) return 'N/A'

  const sizes = ['B', 'KB', 'MB', 'GB']
  if (bytes === 0) return '0 B'

  const i = Math.floor(Math.log(bytes) / Math.log(1024))
  return Math.round(bytes / Math.pow(1024, i) * 100) / 100 + ' ' + sizes[i]
}

const openEditModal = (document: Document): void => {
  documentToEdit.value = document
  editForm.value = {
    name: document.name,
    version: document.version,
    document_type: document.document_type || '',
    description: document.description || ''
  }
  showEditModal.value = true
}

const cancelEdit = (): void => {
  if (isUpdating.value) return
  showEditModal.value = false
  documentToEdit.value = null
  editForm.value = {
    name: '',
    version: '',
    document_type: '',
    description: ''
  }
}

const updateDocument = async (): Promise<void> => {
  if (!documentToEdit.value || !isFormValid.value) return

  isUpdating.value = true

  try {
    const updateData: Partial<EditForm> = {}

    // Only include fields that have changed
    if (editForm.value.name !== documentToEdit.value.name) {
      updateData.name = editForm.value.name.trim()
    }
    if (editForm.value.version !== documentToEdit.value.version) {
      updateData.version = editForm.value.version.trim()
    }
    if (editForm.value.document_type !== (documentToEdit.value.document_type || '')) {
      updateData.document_type = editForm.value.document_type
    }
    if (editForm.value.description !== (documentToEdit.value.description || '')) {
      updateData.description = editForm.value.description.trim()
    }

    // If no changes, just close the modal
    if (Object.keys(updateData).length === 0) {
      showSuccess('No changes detected')
      cancelEdit()
      return
    }

    const response = await $axios.patch(`/api/v1/documents/${documentToEdit.value.id}`, updateData)

    // Update the document in the list with the response data
    const updatedDocument = response.data
    const index = parsedDocumentsData.value.findIndex(
      item => item.document.id === documentToEdit.value!.id
    )

    if (index !== -1) {
      parsedDocumentsData.value[index].document = { ...parsedDocumentsData.value[index].document, ...updatedDocument }
    }

    showSuccess(`Document "${updatedDocument.name}" updated successfully`)
    cancelEdit()
  } catch (err) {
    console.error('Error updating document:', err)
    let errorMessage = 'Failed to update document'

    if (isAxiosError(err)) {
      errorMessage = err.response?.data?.detail || errorMessage
    }

    showError(errorMessage)
  } finally {
    isUpdating.value = false
  }
}

const confirmDelete = (document: Document): void => {
  documentToDelete.value = document
  showDeleteModal.value = true
}

const cancelDelete = (): void => {
  if (isDeleting.value) return // Prevent canceling during deletion
  showDeleteModal.value = false
  documentToDelete.value = null
}

const deleteDocument = async (): Promise<void> => {
  if (!documentToDelete.value) return

  isDeleting.value = documentToDelete.value.id

  try {
    await $axios.delete(`/api/v1/documents/${documentToDelete.value.id}`)

    // Remove the deleted document from the list
    parsedDocumentsData.value = parsedDocumentsData.value.filter(
      item => item.document.id !== documentToDelete.value!.id
    )

    showSuccess(`Document "${documentToDelete.value.name}" deleted successfully`)

    // Clear deleting state before closing modal
    isDeleting.value = null
    cancelDelete()
  } catch (err) {
    console.error('Error deleting document:', err)
    let errorMessage = 'Failed to delete document'

    if (isAxiosError(err)) {
      errorMessage = err.response?.data?.detail || errorMessage
    }

    showError(errorMessage)
    isDeleting.value = null
  }
}

const parseDocumentsData = (): void => {
  try {
    if (props.documentsDataElementId) {
      // Get data from JSON script element
      const element = document.getElementById(props.documentsDataElementId)
      if (element && element.textContent) {
        const parsed = JSON.parse(element.textContent)
        if (Array.isArray(parsed)) {
          parsedDocumentsData.value = parsed
          return
        }
      }
    }

    // If no valid data provided, show empty state
    parsedDocumentsData.value = []
  } catch (err) {
    console.error('Error parsing documents data:', err)
    error.value = 'Failed to parse documents data'
    parsedDocumentsData.value = []
  }
}

onMounted(() => {
  parseDocumentsData()
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
</style>