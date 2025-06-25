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

// Extend window type to include refresh functions
declare global {
  interface Window {
    refreshComponents?: () => void;
  }
}

const componentName = ref('')
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
        metadata: {}
      })
    })

    const data = await response.json()

    if (response.ok) {
      showSuccess('Component created successfully!')
      resetForm()
      closeModal()
      // Refresh the components list
      if (typeof window.refreshComponents === 'function') {
        window.refreshComponents()
      }
    } else {
      errorMessage.value = data.detail || 'An error occurred'
      if (response.status === 403 && data.detail?.includes('maximum')) {
        // This is a billing limit error - show it as a global error too
        showError(data.detail)
      }
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
  errorMessage.value = ''
  isLoading.value = false
}

const closeModal = () => {
  const modal = document.getElementById('addComponentModal')
  if (modal) {
    const bootstrap = (window as unknown as { bootstrap?: { Modal?: { getInstance(el: HTMLElement): { hide(): void } | null } } }).bootstrap
    const bootstrapModal = bootstrap?.Modal?.getInstance(modal)
    if (bootstrapModal) {
      bootstrapModal.hide()
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