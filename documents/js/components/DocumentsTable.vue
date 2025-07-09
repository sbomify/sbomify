<template>
  <!-- Wrap in StandardCard only for non-public views -->
  <StandardCard
    v-if="!isPublicView"
    title="Documents"
    :collapsible="true"
    :defaultExpanded="true"
    storageKey="documents-table"
  >
    <!-- Table content -->
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
            <th scope="col">Artifact Type</th>
            <th scope="col">Type</th>
            <th scope="col">Version</th>
            <th scope="col">Created</th>
            <th scope="col">Releases</th>
            <th scope="col">Actions</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in parsedDocumentsData" :key="item.document.id">
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
              <div v-if="item.releases && item.releases.length > 0" class="release-badges">
                <span
                  v-for="release in item.releases"
                  :key="release.id"
                  :class="['badge', 'me-1', 'mb-1', getReleaseBadge(release)]"
                  :title="`${release.product_name} - ${release.name}`"
                >
                  {{ release.name }}
                  <span v-if="release.is_prerelease" class="ms-1">⚠️</span>
                </span>
              </div>
              <span v-else class="text-muted">None</span>
            </td>
            <td>
              <div class="d-flex gap-2">
                <a :href="`/api/v1/documents/${item.document.id}/download`" title="Download" class="btn btn-outline-primary btn-sm action-btn">
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
  </StandardCard>

  <div v-else>
    <!-- Table content (same as above but without StandardCard wrapper) -->
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
            <th scope="col">Artifact Type</th>
            <th scope="col">Type</th>
            <th scope="col">Version</th>
            <th scope="col">Created</th>
            <th scope="col">Releases</th>
            <th scope="col">Actions</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in parsedDocumentsData" :key="item.document.id">
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
              <div v-if="item.releases && item.releases.length > 0" class="release-badges">
                <span
                  v-for="release in item.releases"
                  :key="release.id"
                  :class="['badge', 'me-1', 'mb-1', getReleaseBadge(release)]"
                  :title="`${release.product_name} - ${release.name}`"
                >
                  {{ release.name }}
                  <span v-if="release.is_prerelease" class="ms-1">⚠️</span>
                </span>
              </div>
              <span v-else class="text-muted">None</span>
            </td>
            <td>
              <div class="d-flex gap-2">
                <a :href="`/api/v1/documents/${item.document.id}/download`" title="Download" class="btn btn-outline-primary btn-sm action-btn">
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
import { ref, onMounted, computed } from 'vue'
import { showSuccess, showError } from '../../../core/js/alerts'
import DeleteConfirmationModal from '../../../core/js/components/DeleteConfirmationModal.vue'
import StandardCard from '../../../core/js/components/StandardCard.vue'

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

const props = defineProps<{
  documentsDataElementId?: string
  componentId?: string
  hasCrudPermissions?: boolean
  isPublicView?: boolean
}>()

const parsedDocumentsData = ref<DocumentData[]>([])
const error = ref<string | null>(null)
const showDeleteModal = ref(false)
const documentToDelete = ref<Document | null>(null)
const isDeleting = ref<string | null>(null)

const hasData = computed(() => parsedDocumentsData.value.length > 0)

const hasCrudPermissions = computed(() => {
  if (typeof props.hasCrudPermissions === 'string') {
    return props.hasCrudPermissions === 'true'
  }
  return props.hasCrudPermissions || false
})

const isPublicView = computed(() => props.isPublicView === true)

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

const truncateText = (text: string, maxLength: number): string => {
  if (text.length <= maxLength) return text
  return text.substring(0, maxLength - 3) + '...'
}

const getReleaseBadge = (release: Release): string => {
  if (release.is_latest) {
    return 'bg-success'
  } else if (release.is_prerelease) {
    return 'bg-warning text-dark'
  } else if (release.is_public) {
    return 'bg-primary'
  } else {
    return 'bg-secondary'
  }
}



const getDocumentTypeDisplay = (type: string): string => {
  const typeMap: { [key: string]: string } = {
    'specification': 'Specification',
    'manual': 'Manual',
    'report': 'Report',
    'license': 'License',
    'readme': 'README',
    'changelog': 'Changelog',
    'documentation': 'Documentation',
    'compliance': 'Compliance',
    'other': 'Other'
  }
  return typeMap[type] || 'Document'
}

const formatDate = (dateString: string): string => {
  try {
    const date = new Date(dateString)
    return date.toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric'
    })
  } catch {
    return 'Invalid date'
  }
}





const parseDocumentsData = (): void => {
  try {
    console.log('📄 Parsing documents data with elementId:', props.documentsDataElementId)

    if (props.documentsDataElementId) {
      // Get data from JSON script element
      const element = document.getElementById(props.documentsDataElementId)
      console.log('📄 Found element:', element)

      if (element && element.textContent) {
        console.log('📄 Element content length:', element.textContent.length)
        console.log('📄 Element content (first 100 chars):', element.textContent.substring(0, 100))

        const parsed = JSON.parse(element.textContent)
        console.log('📄 Parsed data:', parsed)
        console.log('📄 Is array?', Array.isArray(parsed))
        console.log('📄 Array length:', Array.isArray(parsed) ? parsed.length : 'N/A')

        if (Array.isArray(parsed)) {
          parsedDocumentsData.value = parsed
          console.log('📄 Set parsedDocumentsData, length:', parsedDocumentsData.value.length)
          return
        } else {
          console.log('📄 Parsed data is not an array, type:', typeof parsed)
        }
      } else {
        console.log('📄 Element not found or has no content. Element:', !!element, 'Content:', !!element?.textContent)
      }
    } else {
      console.log('📄 No documentsDataElementId provided')
    }

    // If no valid data provided, show empty state
    console.log('📄 Setting empty array as fallback')
    parsedDocumentsData.value = []
  } catch (err) {
    console.error('📄 Error parsing documents data:', err)
    error.value = 'Failed to parse documents data'
    parsedDocumentsData.value = []
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
    const response = await fetch(`/api/v1/documents/${documentToDelete.value.id}`, {
      method: 'DELETE',
      headers: {
        'X-CSRFToken': getCsrfToken()
      }
    })

    if (response.ok) {
      // Remove the document from the local data
      parsedDocumentsData.value = parsedDocumentsData.value.filter(
        item => item.document.id !== documentToDelete.value!.id
      )

      showSuccess(`Document "${documentToDelete.value.name}" deleted successfully`)

      // Clear deleting state before closing modal
      isDeleting.value = null
      cancelDelete()
    } else {
      const errorData = await response.json()
      throw new Error(errorData.detail || 'Failed to delete document')
    }
  } catch (err: any) {
    console.error('Error deleting document:', err)
    showError(err.message || 'Failed to delete document')
    isDeleting.value = null
  }
}

const getCsrfToken = (): string => {
  const token = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content')
  if (token) return token

  const cookies = document.cookie.split(';')
  for (const cookie of cookies) {
    const [name, value] = cookie.trim().split('=')
    if (name === 'csrftoken') {
      return value
    }
  }
  return ''
}

onMounted(() => {
  console.log('📄 DocumentsTable onMounted, props:', {
    documentsDataElementId: props.documentsDataElementId,
    componentId: props.componentId,
    hasCrudPermissions: props.hasCrudPermissions,
    isPublicView: props.isPublicView
  })

  parseDocumentsData()

  console.log('📄 After initial parse - hasData:', hasData.value, 'error:', error.value)

  // Try again after a delay in case of timing issues
  setTimeout(() => {
    console.log('📄 Retry parsing after delay...')
    parseDocumentsData()
    console.log('📄 After retry - hasData:', hasData.value, 'error:', error.value)
  }, 100)
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