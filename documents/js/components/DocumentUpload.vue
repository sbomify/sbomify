<template>
  <StandardCard
    title="Upload Document File"
    :collapsible="true"
    :default-expanded="false"
    info-icon="fas fa-info-circle"
    storage-key="document-upload"
  >
    <template #info-notice>
      <strong>Document Upload:</strong> Upload documents like specifications, manuals, reports, compliance documents, or any file related to your component. You can specify a version and description during upload.
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

        <!-- Technical Documentation -->
        <optgroup label="Technical Documentation">
          <option value="specification">Specification</option>
          <option value="manual">Manual</option>
          <option value="readme">README</option>
          <option value="documentation">Documentation</option>
          <option value="build-instructions">Build Instructions</option>
          <option value="configuration">Configuration</option>
        </optgroup>

        <!-- Legal and Compliance -->
        <optgroup label="Legal and Compliance">
          <option value="license">License</option>
          <option value="compliance">Compliance</option>
          <option value="evidence">Evidence</option>
        </optgroup>

        <!-- Release Information -->
        <optgroup label="Release Information">
          <option value="changelog">Changelog</option>
          <option value="release-notes">Release Notes</option>
        </optgroup>

        <!-- Security Documents -->
        <optgroup label="Security Documents">
          <option value="security-advisory">Security Advisory</option>
          <option value="vulnerability-report">Vulnerability Report</option>
          <option value="threat-model">Threat Model</option>
          <option value="risk-assessment">Risk Assessment</option>
          <option value="pentest-report">Penetration Test Report</option>
        </optgroup>

        <!-- Analysis Reports -->
        <optgroup label="Analysis Reports">
          <option value="static-analysis">Static Analysis Report</option>
          <option value="dynamic-analysis">Dynamic Analysis Report</option>
          <option value="quality-metrics">Quality Metrics</option>
          <option value="maturity-report">Maturity Report</option>
          <option value="report">Report</option>
        </optgroup>

        <!-- Other -->
        <optgroup label="Other">
          <option value="other">Other</option>
        </optgroup>
      </select>
      <div class="form-text">Select the type of document you're uploading. This helps with SBOM generation and compliance.</div>
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
         :class="{ 'drag-over': isDragOver, 'file-selected': selectedFile && !isUploading }"
         @drop="handleDrop"
         @dragover.prevent="isDragOver = true"
         @dragleave="isDragOver = false"
         @dragenter.prevent>

      <div v-if="!selectedFile && !isUploading" class="upload-content">
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

      <div v-if="selectedFile && !isUploading" class="file-selected-content">
        <div class="file-icon">
          <i class="fas fa-file-alt"></i>
        </div>
        <div class="file-info">
          <p class="file-name">{{ selectedFile.name }}</p>
          <p class="file-size">{{ formatFileSize(selectedFile.size) }}</p>
        </div>
        <button
          type="button"
          class="btn btn-sm btn-outline-secondary"
          @click="clearSelectedFile"
          title="Remove file"
        >
          <i class="fas fa-times"></i>
        </button>
      </div>

      <div v-if="isUploading" class="upload-progress">
        <div class="spinner-border text-primary" role="status">
          <span class="visually-hidden">Uploading...</span>
        </div>
        <p class="mt-2">Uploading and processing document...</p>
      </div>
    </div>

    <div v-if="selectedFile && !isUploading" class="d-flex justify-content-between align-items-center mt-3">
      <div class="text-muted small">
        <i class="fas fa-info-circle"></i>
        Review your document details and click "Save Document" to upload.
      </div>
      <div>
        <button
          type="button"
          class="btn btn-outline-secondary me-2"
          @click="clearSelectedFile"
        >
          Cancel
        </button>
        <button
          type="button"
          class="btn btn-primary"
          @click="saveDocument"
          :disabled="!isFormValid"
        >
          <i class="fas fa-save me-1"></i>
          Save Document
        </button>
      </div>
    </div>
  </StandardCard>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import StandardCard from '../../../core/js/components/StandardCard.vue'
import { showSuccess, showError } from '../../../core/js/alerts'

interface Props {
  componentId: string
}

const props = defineProps<Props>()

const isDragOver = ref(false)
const isUploading = ref(false)
const selectedFile = ref<File | null>(null)
const fileInput = ref<HTMLInputElement>()
const documentVersion = ref('1.0')
const documentType = ref('')
const documentDescription = ref('')

const isFormValid = computed(() => {
  return selectedFile.value && documentVersion.value.trim().length > 0
})

const formatFileSize = (bytes: number): string => {
  if (bytes === 0) return '0 Bytes'
  const k = 1024
  const sizes = ['Bytes', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i]
}

const validateFile = (file: File): string | null => {
  // Check file size (max 50MB)
  const maxSize = 50 * 1024 * 1024
  if (file.size > maxSize) {
    return 'File size must be less than 50MB'
  }

  return null
}

const clearSelectedFile = (): void => {
  selectedFile.value = null
  if (fileInput.value) {
    fileInput.value.value = ''
  }
}

const saveDocument = async (): Promise<void> => {
  if (!selectedFile.value) {
    showError('Please select a file to upload')
    return
  }

  const validationError = validateFile(selectedFile.value)
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
    formData.append('document_file', selectedFile.value)
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
      selectedFile.value = null
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
    const file = files[0]
    const validationError = validateFile(file)
    if (validationError) {
      showError(validationError)
      return
    }
    selectedFile.value = file
  }
}

const handleFileSelect = (event: Event): void => {
  const target = event.target as HTMLInputElement
  const files = target.files
  if (files && files.length > 0) {
    const file = files[0]
    const validationError = validateFile(file)
    if (validationError) {
      showError(validationError)
      return
    }
    selectedFile.value = file
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

.upload-area.file-selected {
  border-color: #22c55e;
  background-color: #f0fdf4;
  cursor: default;
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

.file-selected-content {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 1rem;
  background-color: #ffffff;
  border-radius: 6px;
  border: 1px solid #e2e8f0;
}

.file-icon {
  font-size: 2rem;
  color: #22c55e;
}

.file-info {
  flex-grow: 1;
  text-align: left;
}

.file-name {
  font-weight: 600;
  color: #1f2937;
  margin-bottom: 0.25rem;
}

.file-size {
  font-size: 0.875rem;
  color: #6b7280;
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