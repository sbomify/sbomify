<template>
  <div id="addProjectModal" class="modal fade" data-bs-backdrop="static" tabindex="-1" aria-labelledby="addProjectModalLabel" aria-hidden="true">
    <div class="modal-dialog modal-dialog-centered">
      <div class="modal-content border-0">
        <div class="modal-header border-bottom-0 pb-0">
          <h4 id="addProjectModalLabel" class="modal-title text-secondary">Add Project</h4>
          <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
        </div>
        <div class="modal-body pt-3">
          <form @submit.prevent="createProject">
            <div class="mb-4">
              <label class="form-label text-secondary fw-medium" for="projectName">
                Name
                <span class="text-danger">*</span>
              </label>
              <input
                id="projectName"
                ref="nameInput"
                v-model="projectName"
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
                {{ isLoading ? 'Creating...' : 'Create Project' }}
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

const projectName = ref('')
const isLoading = ref(false)
const errorMessage = ref('')
const nameInput = ref<HTMLInputElement>()

const createProject = async () => {
  if (!projectName.value.trim()) {
    errorMessage.value = 'Project name is required'
    return
  }

  isLoading.value = true
  errorMessage.value = ''

  try {
    const response = await fetch('/api/v1/projects', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCsrfToken(),
        'Accept': 'application/json'
      },
      body: JSON.stringify({
        name: projectName.value.trim(),
        metadata: {}
      })
    })

    const data = await response.json()

    if (response.ok) {
      showSuccess('Project created successfully!')
      resetForm()
      closeModal()
      // Emit event to refresh the projects list
      eventBus.emit(EVENTS.REFRESH_PROJECTS)
    } else {
      // Show all API errors as global notifications for consistency (same style as success)
      showError(data.detail || 'An error occurred while creating the project')
    }
  } catch (error) {
    console.error('Error creating project:', error)
    errorMessage.value = 'An error occurred while creating the project'
    showError('An error occurred while creating the project')
  } finally {
    isLoading.value = false
  }
}

const resetForm = () => {
  projectName.value = ''
  errorMessage.value = ''
  isLoading.value = false
}

const closeModal = () => {
  const modal = document.getElementById('addProjectModal')
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
  const modal = document.getElementById('addProjectModal')
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