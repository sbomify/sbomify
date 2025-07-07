<template>
  <StandardCard
    title="Product Links"
    variant="default"
    shadow="sm"
  >
    <template #header-actions>
      <button
        v-if="canManageLinks"
        class="btn btn-primary btn-sm"
        @click="showAddModal = true"
      >
        <i class="fas fa-plus me-1"></i>
        Add Link
      </button>

    </template>

    <!-- Loading State -->
    <div v-if="isLoading" class="d-flex justify-content-center py-4">
      <div class="spinner-border text-primary" role="status">
        <span class="visually-hidden">Loading...</span>
      </div>
    </div>

    <!-- Error State -->
    <div v-else-if="error" class="alert alert-danger">
      <p class="mb-0">{{ error }}</p>
    </div>

    <!-- Empty State -->
    <div v-else-if="!hasData" class="text-center py-4 text-muted">
      <i class="fas fa-link fa-2x mb-3"></i>
      <div v-if="!hasCrudPermissions">
        <p class="mb-0">No product links available</p>
        <small>This product does not have any links defined</small>
      </div>
      <div v-else>
        <p class="mb-0">No product links added</p>
        <small>Add links like website, support, documentation, etc. to provide additional information about this product</small>
      </div>
    </div>

    <!-- Links Table -->
    <div v-else class="table-responsive">
      <table class="table table-sm">
        <thead>
          <tr>
            <th style="width: 20%">Type</th>
            <th style="width: 30%">Title</th>
            <th style="width: 35%">URL</th>
            <th v-if="canManageLinks" style="width: 15%" class="text-end">Actions</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="link in links" :key="link.id">
            <td>
              <span class="badge bg-secondary-subtle text-secondary">
                {{ getLinkTypeDisplayName(link.link_type) }}
              </span>
            </td>
            <td>
              <strong>{{ link.title }}</strong>
              <div v-if="link.description" class="text-muted small">
                {{ link.description }}
              </div>
            </td>
            <td>
              <a :href="link.url" target="_blank" rel="noopener noreferrer" class="text-primary text-decoration-none">
                {{ truncateUrl(link.url) }}
                <i class="fas fa-external-link-alt ms-1 small"></i>
              </a>
            </td>
            <td v-if="canManageLinks" class="text-end">
              <div class="btn-group btn-group-sm">
                <button
                  class="btn btn-outline-primary btn-sm"
                  title="Edit"
                  @click="editLink(link)"
                >
                  <i class="fas fa-edit"></i>
                </button>
                <button
                  class="btn btn-outline-danger btn-sm"
                  title="Delete"
                  @click="deleteLink(link)"
                >
                  <i class="fas fa-trash"></i>
                </button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Add/Edit Modal -->
    <div v-if="showAddModal || showEditModal" class="modal fade show d-block" tabindex="-1" style="background-color: rgba(0,0,0,0.5)">
      <div class="modal-dialog modal-lg">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title">
              {{ showEditModal ? 'Edit Link' : 'Add Link' }}
            </h5>
            <button type="button" class="btn-close" @click="closeModal"></button>
          </div>
          <div class="modal-body">
            <form @submit.prevent="submitForm">
              <div class="mb-3">
                <label class="form-label">Link Type <span class="text-danger">*</span></label>
                <select v-model="form.link_type" class="form-select" required>
                  <option value="">Select type...</option>
                  <option v-for="(label, value) in linkTypes" :key="value" :value="value">
                    {{ label }}
                  </option>
                </select>
              </div>
              <div class="mb-3">
                <label class="form-label">Title <span class="text-danger">*</span></label>
                <input
                  v-model="form.title"
                  type="text"
                  class="form-control"
                  :class="{ 'is-invalid': formError }"
                  required
                  placeholder="Enter link title"
                />
              </div>
              <div class="mb-3">
                <label class="form-label">URL <span class="text-danger">*</span></label>
                <input
                  v-model="form.url"
                  type="url"
                  class="form-control"
                  :class="{ 'is-invalid': formError }"
                  required
                  placeholder="https://example.com"
                />
              </div>
              <div class="mb-3">
                <label class="form-label">Description</label>
                <textarea
                  v-model="form.description"
                  class="form-control"
                  rows="3"
                  placeholder="Optional description of this link"
                ></textarea>
              </div>
              <div v-if="formError" class="alert alert-danger">
                {{ formError }}
              </div>
            </form>
          </div>
          <div class="modal-footer">
            <button type="button" class="btn btn-secondary" @click="closeModal">Cancel</button>
            <button type="button" class="btn btn-primary" :disabled="isSubmitting" @click="submitForm">
              {{ isSubmitting ? 'Saving...' : (showEditModal ? 'Update' : 'Add') }}
            </button>
          </div>
        </div>
      </div>
    </div>
  </StandardCard>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import $axios from '../utils'
import { showSuccess, showError } from '../alerts'
import { isAxiosError } from 'axios'
import StandardCard from './StandardCard.vue'

// Types
interface ProductLink {
  id: string
  link_type: string
  title: string
  url: string
  description: string
  created_at: string
}

interface Props {
  productId: string
  hasCrudPermissions?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  hasCrudPermissions: false
})

// State
const links = ref<ProductLink[]>([])
const isLoading = ref(false)
const error = ref<string | null>(null)
const showAddModal = ref(false)
const showEditModal = ref(false)
const isSubmitting = ref(false)
const formError = ref('')
const editingLink = ref<ProductLink | null>(null)

// Form state
const form = ref({
  link_type: '',
  title: '',
  url: '',
  description: ''
})

// Link types mapping
const linkTypes = {
  'website': 'Website',
  'support': 'Support',
  'documentation': 'Documentation',
  'repository': 'Repository',
  'changelog': 'Changelog',
  'release_notes': 'Release Notes',
  'security': 'Security',
  'issue_tracker': 'Issue Tracker',
  'download': 'Download',
  'chat': 'Chat/Community',
  'social': 'Social Media',
  'other': 'Other'
}

// Computed
const hasData = computed(() => links.value.length > 0)
const canManageLinks = computed(() => props.hasCrudPermissions)

// Methods
const getLinkTypeDisplayName = (type: string): string => {
  return linkTypes[type as keyof typeof linkTypes] || type
}

const truncateUrl = (url: string): string => {
  if (url.length <= 50) return url
  return url.substring(0, 47) + '...'
}

const loadLinks = async () => {
  isLoading.value = true
  error.value = null

  try {
    const response = await $axios.get(`/api/v1/products/${props.productId}/links`)
    links.value = response.data
  } catch (err) {
    console.error('Error loading links:', err)
    error.value = 'Failed to load links'

    if (isAxiosError(err)) {
      showError(err.response?.data?.detail || 'Failed to load links')
    } else {
      showError('Failed to load links')
    }
  } finally {
    isLoading.value = false
  }
}

const resetForm = () => {
  form.value = {
    link_type: '',
    title: '',
    url: '',
    description: ''
  }
  formError.value = ''
  editingLink.value = null
}

const closeModal = () => {
  showAddModal.value = false
  showEditModal.value = false
  resetForm()
}

const editLink = (link: ProductLink) => {
  editingLink.value = link
  form.value = {
    link_type: link.link_type,
    title: link.title,
    url: link.url,
    description: link.description
  }
  showEditModal.value = true
}

const submitForm = async () => {
  if (!form.value.link_type || !form.value.title.trim() || !form.value.url.trim()) {
    formError.value = 'Link type, title, and URL are required'
    return
  }

  isSubmitting.value = true
  formError.value = ''

  try {
    if (showEditModal.value && editingLink.value) {
      // Update existing link
      const response = await $axios.put(
        `/api/v1/products/${props.productId}/links/${editingLink.value.id}`,
        {
          link_type: form.value.link_type,
          title: form.value.title.trim(),
          url: form.value.url.trim(),
          description: form.value.description.trim()
        }
      )

      // Update the link in the list
      const index = links.value.findIndex(l => l.id === editingLink.value!.id)
      if (index !== -1) {
        links.value[index] = response.data
      }

      showSuccess('Link updated successfully!')
    } else {
      // Create new link
      const response = await $axios.post(`/api/v1/products/${props.productId}/links`, {
        link_type: form.value.link_type,
        title: form.value.title.trim(),
        url: form.value.url.trim(),
        description: form.value.description.trim()
      })

      links.value.push(response.data)
      showSuccess('Link added successfully!')
    }

    closeModal()
  } catch (err) {
    console.error('Error saving link:', err)

    if (isAxiosError(err)) {
      formError.value = err.response?.data?.detail || 'Failed to save link'
      showError(err.response?.data?.detail || 'Failed to save link')
    } else {
      formError.value = 'Failed to save link'
      showError('Failed to save link')
    }
  } finally {
    isSubmitting.value = false
  }
}

const deleteLink = async (link: ProductLink) => {
  if (!confirm(`Are you sure you want to delete the ${getLinkTypeDisplayName(link.link_type)} link "${link.title}"?`)) {
    return
  }

  try {
    await $axios.delete(`/api/v1/products/${props.productId}/links/${link.id}`)

    // Remove from list
    links.value = links.value.filter(l => l.id !== link.id)
    showSuccess('Link deleted successfully!')
  } catch (err) {
    console.error('Error deleting link:', err)

    if (isAxiosError(err)) {
      showError(err.response?.data?.detail || 'Failed to delete link')
    } else {
      showError('Failed to delete link')
    }
  }
}

// Lifecycle
onMounted(() => {
  loadLinks()
})

// Expose methods for external use
defineExpose({
  loadLinks
})
</script>

<style scoped>
.modal.show {
  animation: fadeIn 0.15s ease-in-out;
}

@keyframes fadeIn {
  from {
    opacity: 0;
  }
  to {
    opacity: 1;
  }
}

.btn-group-sm .btn {
  padding: 0.25rem 0.5rem;
  font-size: 0.75rem;
}

.table td {
  vertical-align: middle;
}
</style>