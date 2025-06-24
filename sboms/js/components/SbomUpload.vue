<template>
  <StandardCard
    title="Upload SBOM File"
    :collapsible="true"
    :default-expanded="false"
    info-icon="fas fa-info-circle"
    storage-key="sbom-upload"
  >
    <template #info-notice>
      <strong>Recommended:</strong> Use the CI/CD Integration section below for automated SBOM uploads. Manual uploads are useful for one-time uploads, testing, or when automated workflows aren't available.
    </template>
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
            <strong>Drop your SBOM file here</strong> or
            <label class="upload-link">
                             <input ref="fileInput"
                      type="file"
                      accept=".json,.spdx,.cdx"
                      style="display: none;"
                      @change="handleFileSelect">
              click to browse
            </label>
          </p>
          <p class="upload-hint">
            Supports CycloneDX (.json, .cdx) and SPDX (.json, .spdx) formats
          </p>
        </div>

        <div v-if="isUploading" class="upload-progress">
          <div class="spinner-border text-primary" role="status">
            <span class="visually-hidden">Uploading...</span>
          </div>
          <p class="mt-2">Uploading and processing SBOM...</p>
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

const validateFile = (file: File): string | null => {
  // Check file size (max 10MB)
  const maxSize = 10 * 1024 * 1024
  if (file.size > maxSize) {
    return 'File size must be less than 10MB'
  }

  // Check file type
  const allowedTypes = ['application/json', 'text/plain']
  const allowedExtensions = ['.json', '.spdx', '.cdx']
  const fileExtension = file.name.toLowerCase().slice(file.name.lastIndexOf('.'))

  if (!allowedTypes.includes(file.type) && !allowedExtensions.includes(fileExtension)) {
    return 'Please select a valid SBOM file (.json, .spdx, .cdx)'
  }

  return null
}

const uploadFile = async (file: File): Promise<void> => {
  const validationError = validateFile(file)
  if (validationError) {
    showError(validationError)
    return
  }

  isUploading.value = true

  try {
    const formData = new FormData()
    formData.append('sbom_file', file)
    formData.append('component_id', props.componentId)

    const response = await fetch(`/api/v1/sboms/upload-file/${props.componentId}`, {
      method: 'POST',
      body: formData,
      headers: {
        'X-CSRFToken': getCsrfToken()
      }
    })

    const data = await response.json()

    if (response.ok) {
      showSuccess('SBOM uploaded successfully!')
      // Refresh the page after 2 seconds to show the new SBOM
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
  const token = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content')
  if (!token) {
    // Fallback to cookie method
    const cookieValue = document.cookie
      .split('; ')
      .find(row => row.startsWith('csrftoken='))
      ?.split('=')[1]
    return cookieValue || ''
  }
  return token
}
</script>

<style scoped>
.upload-area {
  border: 2px dashed #dee2e6;
  border-radius: 8px;
  padding: 3rem 2rem;
  text-align: center;
  background-color: #f8f9fa;
  transition: all 0.3s ease;
  cursor: pointer;
}

.upload-area.drag-over {
  border-color: #0d6efd;
  background-color: #e7f3ff;
}

.upload-area.uploading {
  border-color: #6c757d;
  background-color: #e9ecef;
  cursor: not-allowed;
}

.upload-content {
  color: #6c757d;
}

.upload-icon {
  font-size: 3rem;
  color: #adb5bd;
  margin-bottom: 1rem;
}

.upload-text {
  font-size: 1.1rem;
  margin-bottom: 0.5rem;
}

.upload-link {
  color: #0d6efd;
  cursor: pointer;
  text-decoration: underline;
}

.upload-link:hover {
  color: #0a58ca;
}

.upload-hint {
  font-size: 0.9rem;
  color: #adb5bd;
  margin-bottom: 0;
}

.upload-progress {
  color: #6c757d;
}
</style>