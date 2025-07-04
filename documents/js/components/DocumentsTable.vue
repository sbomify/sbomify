<template>
  <div v-if="error" class="alert alert-danger">
    {{ error }}
  </div>

  <div v-else-if="!hasData" class="text-center text-muted py-4">
    <i class="fas fa-file-alt fa-3x mb-3"></i>
    <p>No documents found for this component.</p>
  </div>

  <div v-else class="data-table">
    <table class="table table-striped">
      <thead>
        <tr>
          <th scope="col">Name</th>
          <th scope="col">Type</th>
          <th scope="col">Version</th>
          <th scope="col">Size</th>
          <th scope="col">Created</th>
          <th scope="col">Actions</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="item in parsedDocumentsData" :key="item.document.id">
          <td>
            <div class="d-flex align-items-center">
              <i class="fas fa-file-alt text-primary me-2"></i>
              <span class="fw-medium">{{ item.document.name }}</span>
            </div>
          </td>
          <td>
            <span class="badge bg-secondary">{{ getDocumentTypeDisplay(item.document.document_type) }}</span>
          </td>
          <td>
            <span class="text-muted">{{ item.document.version }}</span>
          </td>
          <td>
            <span class="text-muted small">{{ formatFileSize(item.document.file_size) }}</span>
          </td>
          <td>
            <span class="text-muted small">{{ formatDate(item.document.created_at) }}</span>
          </td>
          <td>
            <div class="btn-group btn-group-sm">
              <a :href="`/api/v1/documents/${item.document.id}/download`"
                 class="btn btn-outline-primary btn-sm"
                 target="_blank"
                 title="Download document">
                <i class="fas fa-download"></i>
              </a>
            </div>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'

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

const props = defineProps<{
  documentsDataElementId?: string
  componentId?: string
  hasCrudPermissions?: boolean
  isPublicView?: boolean
}>()

const parsedDocumentsData = ref<DocumentData[]>([])
const error = ref<string | null>(null)

const hasData = computed(() => parsedDocumentsData.value.length > 0)



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

const formatFileSize = (bytes: number | null): string => {
  if (!bytes) return 'Unknown'
  if (bytes === 0) return '0 Bytes'
  const k = 1024
  const sizes = ['Bytes', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i]
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
</style>