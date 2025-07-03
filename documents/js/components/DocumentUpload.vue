<template>
  <StandardCard
    title="Upload Document File"
    :collapsible="true"
    :default-expanded="false"
    info-icon="fas fa-info-circle"
    storage-key="document-upload"
  >
    <template #info-notice>
      <strong>Document Upload:</strong> Upload documents like specifications, manuals, reports, or any file related to your component. You can specify a version and description during upload.
    </template>

    <div class="mb-3">
      <label for="document-version" class="form-label">Version <span class="text-danger">*</span></label>
      <input
        id="document-version"
        v-model="documentVersion"
        type="text"
        class="form-control"
        placeholder="e.g., 1.0, v2.1, latest"
        required
      >
      <div class="form-text">Specify the version of this document</div>
    </div>

    <div class="mb-3">
      <label for="document-type" class="form-label">Document Type</label>
      <select id="document-type" v-model="documentType" class="form-select">
        <option value="">Select document type (optional)</option>
        <option value="specification">Specification</option>
        <option value="manual">Manual</option>
        <option value="report">Report</option>
        <option value="license">License</option>
        <option value="readme">README</option>
        <option value="changelog">Changelog</option>
        <option value="documentation">Documentation</option>
        <option value="other">Other</option>
      </select>
    </div>

    <div class="mb-3">
      <label for="document-description" class="form-label">Description</label>
      <textarea
        id="document-description"
        v-model="documentDescription"
        class="form-control"
        rows="3"
        placeholder="Brief description of this document (optional)"
      ></textarea>
    </div>

    <div class="upload-area"
         :class="{ 'drag-over': isDragOver, 'uploading': isUploading }"
         @drop="handleDrop"
         @dragover.prevent="isDragOver = true"
         @dragleave="isDragOver = false"
         @dragenter.prevent>

      <div v-if="!isUploading" class="upload-content">
        <div class="upload-icon">
          <i class="fas fa-cloud-upload-alt"></i>
        </div>
        <p class="upload-text">
          <strong>Drop your document file here</strong> or
          <label class="upload-link">
            <input ref="fileInput"
                   type="file"
                   accept=".pdf,.doc,.docx,.txt,.md,.html,.json,.xml,.yaml,.yml"
                   style="display: none;"
                   @change="handleFileSelect">
            click to browse
          </label>
        </p>
        <p class="upload-hint">
          Supports PDF, Word, text, markdown, and other document formats (max 50MB)
        </p>
      </div>

      <div v-if="isUploading" class="upload-progress">
        <div class="spinner-border text-primary" role="status">
          <span class="visually-hidden">Uploading...</span>
        </div>
        <p class="mt-2">Uploading and processing document...</p>
      </div>
    </div>
  </StandardCard>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import StandardCard from '../../../core/js/components/StandardCard.vue'
import { showSuccess, showError } from '../../../core/js/alerts'

interface Props {
  componentId: string
}

const props = defineProps<Props>()

const isDragOver = ref(false)
const isUploading = ref(false)
const fileInput = ref<HTMLInputElement>()
const documentVersion = ref('1.0')
const documentType = ref('')
const documentDescription = ref('')

const validateFile = (file: File): string | null => {
  // Check file size (max 50MB)
  const maxSize = 50 * 1024 * 1024
  if (file.size > maxSize) {
    return 'File size must be less than 50MB'
  }

  return null
}

const uploadFile = async (file: File): Promise<void> => {
  const validationError = validateFile(file)
  if (validationError) {
    showError(validationError)
    return
  }

  if (!documentVersion.value.trim()) {
    showError('Please specify a document version')
    return
  }

  isUploading.value = true

  try {
    const formData = new FormData()
    formData.append('document_file', file)
    formData.append('component_id', props.componentId)
    formData.append('version', documentVersion.value.trim())
    if (documentType.value) {
      formData.append('document_type', documentType.value)
    }
    if (documentDescription.value.trim()) {
      formData.append('description', documentDescription.value.trim())
    }

    const response = await fetch(`/api/v1/documents/`, {
      method: 'POST',
      body: formData,
      headers: {
        'X-CSRFToken': getCsrfToken()
      }
    })

    const data = await response.json()

    if (response.ok) {
      showSuccess('Document uploaded successfully!')
      // Reset form
      documentVersion.value = '1.0'
      documentType.value = ''
      documentDescription.value = ''
      if (fileInput.value) {
        fileInput.value.value = ''
      }
      // Refresh the page after 2 seconds to show the new document
      setTimeout(() => {
        window.location.reload()
      }, 2000)
    } else {
      showError(data.detail || 'Upload failed')
    }
  } catch {
    showError('Network error occurred. Please try again.')
  } finally {
    isUploading.value = false
  }
}

const handleDrop = (event: DragEvent): void => {
  event.preventDefault()
  isDragOver.value = false

  const files = event.dataTransfer?.files
  if (files && files.length > 0) {
    uploadFile(files[0])
  }
}

const handleFileSelect = (event: Event): void => {
  const target = event.target as HTMLInputElement
  const files = target.files
  if (files && files.length > 0) {
    uploadFile(files[0])
  }
}

const getCsrfToken = (): string => {
  const name = 'csrftoken'
  const cookieValue = document.cookie
    .split('; ')
    .find(row => row.startsWith(name + '='))
    ?.split('=')[1]
  return cookieValue || ''
}
</script>

<style scoped>
.upload-area {
  border: 2px dashed #cbd5e1;
  border-radius: 8px;
  padding: 2rem;
  text-align: center;
  background-color: #f8fafc;
  transition: all 0.2s ease;
  cursor: pointer;
}

.upload-area:hover {
  border-color: #94a3b8;
  background-color: #f1f5f9;
}

.upload-area.drag-over {
  border-color: #3b82f6;
  background-color: #eff6ff;
}

.upload-area.uploading {
  border-color: #22c55e;
  background-color: #f0fdf4;
  cursor: not-allowed;
}

.upload-content {
  color: #64748b;
}

.upload-icon {
  font-size: 3rem;
  color: #94a3b8;
  margin-bottom: 1rem;
}

.upload-text {
  font-size: 1.1rem;
  margin-bottom: 0.5rem;
}

.upload-link {
  color: #3b82f6;
  cursor: pointer;
  text-decoration: underline;
}

.upload-link:hover {
  color: #2563eb;
}

.upload-hint {
  font-size: 0.875rem;
  color: #94a3b8;
  margin-bottom: 0;
}

.upload-progress {
  color: #16a34a;
}

.form-text {
  font-size: 0.875rem;
  color: #6b7280;
}
</style>