<template>
  <div id="addComponentModal" class="modal fade" data-bs-backdrop="static" tabindex="-1" aria-labelledby="addComponentModalLabel" aria-hidden="true">
    <div class="modal-dialog modal-dialog-centered">
      <div class="modal-content border-0">
        <div class="modal-header border-bottom-0 pb-0">
          <h4 id="addComponentModalLabel" class="modal-title text-secondary">Add Component</h4>
          <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
        </div>
        <div class="modal-body pt-3">
          <form @submit.prevent="createComponent">
            <div class="mb-4">
              <label class="form-label text-secondary fw-medium" for="componentName">
                Name
                <span class="text-danger">*</span>
              </label>
              <input
                id="componentName"
                ref="nameInput"
                v-model="componentName"
                type="text"
                class="form-control form-control-lg"
                :class="{ 'is-invalid': errorMessage }"
                required
              />
              <div v-if="errorMessage" class="invalid-feedback d-block">
                {{ errorMessage }}
              </div>
            </div>
            <div class="mb-4">
              <label class="form-label text-secondary fw-medium" for="componentType">
                Type
                <span class="text-danger">*</span>
              </label>
              <select
                id="componentType"
                v-model="componentType"
                class="form-select form-select-lg"
                required
              >
                <option value="sbom">SBOM</option>
                <option value="document">Document</option>
              </select>
              <div class="form-text">
                Choose the type of component you're creating
              </div>
            </div>
            <div class="d-flex justify-content-end gap-2 mt-4">
              <button type="button" class="btn btn-outline-secondary" data-bs-dismiss="modal">Cancel</button>
              <button type="submit" class="btn btn-primary px-4" :disabled="isLoading">
                {{ isLoading ? 'Creating...' : 'Create Component' }}
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, nextTick } from 'vue'
import { showSuccess, showError } from '../../../core/js/alerts'
import { eventBus, EVENTS } from '../../../core/js/utils'

const componentName = ref('')
const componentType = ref('sbom')  // Default to SBOM
const isLoading = ref(false)
const errorMessage = ref('')
const nameInput = ref<HTMLInputElement>()

const createComponent = async () => {
  if (!componentName.value.trim()) {
    errorMessage.value = 'Component name is required'
    return
  }

  isLoading.value = true
  errorMessage.value = ''

  try {
    const response = await fetch('/api/v1/components', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCsrfToken(),
        'Accept': 'application/json'
      },
      body: JSON.stringify({
        name: componentName.value.trim(),
        component_type: componentType.value,
        metadata: {}
      })
    })

    const data = await response.json()

    if (response.ok) {
      showSuccess('Component created successfully!')
      resetForm()
      closeModal()
      // Emit event to refresh the components list
      eventBus.emit(EVENTS.REFRESH_COMPONENTS)
    } else {
      // Show all API errors as global notifications for consistency (same style as success)
      showError(data.detail || 'An error occurred while creating the component')
    }
  } catch (error) {
    console.error('Error creating component:', error)
    errorMessage.value = 'An error occurred while creating the component'
    showError('An error occurred while creating the component')
  } finally {
    isLoading.value = false
  }
}

const resetForm = () => {
  componentName.value = ''
  componentType.value = 'sbom'  // Reset to default
  errorMessage.value = ''
  isLoading.value = false
}

const closeModal = () => {
  const modal = document.getElementById('addComponentModal')
  if (modal) {
    const bootstrap = window.bootstrap
    if (bootstrap && bootstrap.Modal) {
      const bootstrapModal = bootstrap.Modal.getInstance(modal)
      if (bootstrapModal) {
        bootstrapModal.hide()
      }
    }
  }
}

const getCsrfToken = (): string => {
  const csrfCookie = document.cookie
    .split('; ')
    .find(row => row.startsWith('csrftoken='))
  return csrfCookie ? csrfCookie.split('=')[1] : ''
}

// Focus input when modal is shown
const setupModalEvents = () => {
  const modal = document.getElementById('addComponentModal')
  if (modal) {
    modal.addEventListener('shown.bs.modal', () => {
      resetForm()
      nextTick(() => {
        nameInput.value?.focus()
      })
    })
  }
}

// Set up modal events on component mount
if (typeof window !== 'undefined') {
  setupModalEvents()
}
</script>