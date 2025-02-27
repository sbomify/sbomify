<template>
  <div class="file-upload-container">
    <div
      class="drop-zone"
      :class="{ 'has-file': modelValue }"
      @drop.prevent="handleDrop"
      @dragover.prevent="dragover = true"
      @dragleave.prevent="dragover = false"
      @click="triggerFileInput"
    >
      <input
        ref="fileInput"
        type="file"
        class="file-input"
        :accept="accept"
        @change="handleFileSelect"
      >

      <div v-if="!modelValue" class="drop-zone-content">
        <i class="icon-upload"></i>
        <p>Drop file here or click to upload</p>
      </div>

      <div v-else-if="isImage" class="image-preview">
        <img :src="previewUrl!" alt="Preview">
      </div>
    </div>

    <div v-if="modelValue" class="file-info">
      <span class="file-name">{{ modelValue.name }}</span>
      <button class="remove-button" @click.prevent="removeFile">
        <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="feather feather-trash-2"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path><line x1="10" y1="11" x2="10" y2="17"></line><line x1="14" y1="11" x2="14" y2="17"></line></svg>
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
  import { ref, computed, onBeforeUnmount, watch } from 'vue'

  defineProps<{
    /** Accept property specifies which file types the file input should accept.
     * For example: "image/*" for all images, ".pdf,.doc" for PDFs and DOC files
     */
    accept: string
  }>()

  const modelValue = defineModel<File | null>()

  const emit = defineEmits<{
    (e: 'file-selected', file: File): void
    (e: 'file-removed'): void
  }>()

  const dragover = ref(false)
  const previewUrl = ref<string | null>(null)
  const fileInput = ref<HTMLInputElement>()

  const createPreviewUrl = (file: File) => {
    if (previewUrl.value) {
      URL.revokeObjectURL(previewUrl.value)
    }
    previewUrl.value = URL.createObjectURL(file)
  }

  onBeforeUnmount(() => {
    if (previewUrl.value) {
      URL.revokeObjectURL(previewUrl.value)
    }
  })

  watch(() => modelValue.value, (newFile) => {
    if (newFile instanceof File) {
      createPreviewUrl(newFile)
    }
  })

  const getImageMimeType = (filename: string): string => {
    const fileExt = filename.split('.').pop()?.toLowerCase() || '';
    const mimeTypes = {
      'png': 'image/png',
      'jpg': 'image/jpeg',
      'jpeg': 'image/jpeg',
      'gif': 'image/gif',
      'svg': 'image/svg+xml',
      'ico': 'image/x-icon'
    };
    return mimeTypes[fileExt as keyof typeof mimeTypes] || 'application/octet-stream';
  }

  const isImage = computed(() => {
    if (!modelValue.value) {
      return false
    }

    const fileType = getImageMimeType(modelValue.value.name)

    return fileType.startsWith('image/')
  })

  const triggerFileInput = () => {
    (fileInput.value as HTMLInputElement).click()
  }

  const handleFileSelect = (event: Event) => {
    const target = event.target as HTMLInputElement
    const file = target.files?.[0]
    if (file) {
      setFile(file)
    }
  }

  const handleDrop = (event: DragEvent) => {
    dragover.value = false
    const file = event.dataTransfer?.files[0]
    if (file) {
      setFile(file)
    }
  }

  const setFile = (file: File) => {
    if (isImage.value) {
      createPreviewUrl(file)
    }
    modelValue.value = file
    emit('file-selected', file)
  }

  const removeFile = () => {
    if (previewUrl.value) {
      URL.revokeObjectURL(previewUrl.value)
    }
    (fileInput.value as HTMLInputElement).value = ''
    modelValue.value = null
    emit('file-removed')
  }

  onBeforeUnmount(() => {
    if (previewUrl.value) {
      URL.revokeObjectURL(previewUrl.value)
    }
  })


</script>


<style scoped>
.file-upload-container {
  width: 100%;
}

.drop-zone {
  position: relative;
  padding: 2rem;
  border: 2px dashed #ccc;
  border-radius: 4px;
  background-color: #f8f8f8;
  cursor: pointer;
  transition: all 0.3s ease;
}

.drop-zone:hover {
  background-color: #eee;
}

.drop-zone.has-file {
  border-style: solid;
}

.file-input {
  display: none;
}

.drop-zone-content {
  text-align: center;
  color: #666;
}

.drop-zone-content i {
  font-size: 2rem;
  margin-bottom: 0.5rem;
}

.image-preview {
  display: flex;
  justify-content: center;
  align-items: center;
  max-height: 200px;
  overflow: hidden;
}

.image-preview img {
  max-width: 100%;
  max-height: 200px;
  object-fit: contain;
}

.file-info {
  display: flex;
  align-items: center;
  margin-top: 0.5rem;
  padding: 0.5rem;
  background-color: #f0f0f0;
  border-radius: 4px;
}

.file-name {
  flex: 1;
  margin-right: 0.5rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.remove-button {
  background: none;
  border: none;
  color: #666;
  cursor: pointer;
  padding: 0.25rem;
}

.remove-button:hover {
  color: #ff4444;
}
</style>