<template>
  <div id="addProductModal" class="modal fade" data-bs-backdrop="static" tabindex="-1" aria-labelledby="addProductModalLabel" aria-hidden="true">
    <div class="modal-dialog modal-dialog-centered">
      <div class="modal-content border-0">
        <div class="modal-header border-bottom-0 pb-0">
          <h4 id="addProductModalLabel" class="modal-title text-secondary">Add Product</h4>
          <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
        </div>
        <div class="modal-body pt-3">
          <form @submit.prevent="createProduct">
            <div class="mb-3">
              <label class="form-label text-secondary fw-medium" for="productName">
                Name
                <span class="text-danger">*</span>
              </label>
              <input
                id="productName"
                ref="nameInput"
                v-model="productName"
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
              <label class="form-label text-secondary fw-medium" for="productDescription">
                Description (Optional)
              </label>
              <textarea
                id="productDescription"
                v-model="productDescription"
                class="form-control"
                rows="3"
                placeholder="Describe your product..."
              ></textarea>
            </div>
            <div class="d-flex justify-content-end gap-2 mt-4">
              <button type="button" class="btn btn-outline-secondary" data-bs-dismiss="modal">Cancel</button>
              <button type="submit" class="btn btn-primary px-4" :disabled="isLoading">
                {{ isLoading ? 'Creating...' : 'Create Product' }}
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

const productName = ref('')
const productDescription = ref('')
const isLoading = ref(false)
const errorMessage = ref('')
const nameInput = ref<HTMLInputElement>()

const createProduct = async () => {
  if (!productName.value.trim()) {
    errorMessage.value = 'Product name is required'
    return
  }

  isLoading.value = true
  errorMessage.value = ''

  try {
    const response = await fetch('/api/v1/products', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCsrfToken(),
        'Accept': 'application/json'
      },
      body: JSON.stringify({
        name: productName.value.trim(),
        description: productDescription.value.trim()
      })
    })

    const data = await response.json()

    if (response.ok) {
      showSuccess('Product created successfully!')
      resetForm()
      closeModal()
      // Emit event to refresh the products list
      eventBus.emit(EVENTS.REFRESH_PRODUCTS)
    } else {
      // Show all API errors as global notifications for consistency (same style as success)
      showError(data.detail || 'An error occurred while creating the product')
    }
  } catch (error) {
    console.error('Error creating product:', error)
    errorMessage.value = 'An error occurred while creating the product'
    showError('An error occurred while creating the product')
  } finally {
    isLoading.value = false
  }
}

const resetForm = () => {
  productName.value = ''
  productDescription.value = ''
  errorMessage.value = ''
  isLoading.value = false
}

const closeModal = () => {
  const modal = document.getElementById('addProductModal')
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
  const modal = document.getElementById('addProductModal')
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