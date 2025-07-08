<template>
  <StandardCard
    title="Product Identifiers"
    variant="default"
    shadow="sm"
  >
    <template #header-actions>
      <button
        v-if="canManageIdentifiers"
        class="btn btn-primary btn-sm"
        @click="showAddModal = true"
      >
        <i class="fas fa-plus me-1"></i>
        Add Identifier
      </button>
      <div v-else-if="hasCrudPermissions && !isFeatureAllowed" class="text-muted small">
        <i class="fas fa-lock me-1"></i>
        Business feature
      </div>
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
      <i class="fas fa-barcode fa-2x mb-3"></i>
      <div v-if="!hasCrudPermissions">
        <p class="mb-0">No product identifiers available</p>
        <small>This product does not have any identifiers defined</small>
      </div>
      <div v-else-if="!isFeatureAllowed">
        <p class="mb-0">Product identifiers are a business feature</p>
        <small>Upgrade to a business or enterprise plan to add identifiers like GTIN, SKU, MPN, etc.</small>
      </div>
      <div v-else>
        <p class="mb-0">No product identifiers added</p>
        <small>Add identifiers like GTIN, SKU, MPN, etc. to help identify this product</small>
      </div>
    </div>

    <!-- Identifiers Table -->
    <div v-else class="table-responsive">
      <table class="table table-sm">
        <thead>
          <tr>
            <th style="width: 25%">Type</th>
            <th style="width: 35%">Value</th>
            <th style="width: 25%" class="text-center">Barcode</th>
            <th v-if="canManageIdentifiers" style="width: 15%" class="text-end">Actions</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="identifier in identifiers" :key="identifier.id">
            <td>
              <span class="badge bg-secondary-subtle text-secondary">
                {{ getIdentifierTypeDisplayName(identifier.identifier_type) }}
              </span>
            </td>
            <td>
              <code class="text-primary">{{ identifier.value }}</code>
            </td>
                                    <td class="text-center">
              <div v-if="canRenderBarcode(identifier.identifier_type)" class="barcode-container">
                                <svg
                  :data-barcode-id="identifier.id"
                  class="barcode-svg"
                ></svg>
                <div v-if="barcodeErrors[identifier.id]" class="text-danger small mt-1">
                  <i class="fas fa-exclamation-triangle me-1"></i>
                  Invalid barcode data
                </div>
              </div>
              <div v-else class="text-muted small text-center">
                <i class="fas fa-info-circle me-1"></i>
                Not Applicable
              </div>
            </td>
            <td v-if="canManageIdentifiers" class="text-end">
              <div class="btn-group btn-group-sm">
                <button
                  class="btn btn-outline-primary btn-sm"
                  title="Edit"
                  @click="editIdentifier(identifier)"
                >
                  <i class="fas fa-edit"></i>
                </button>
                <button
                  class="btn btn-outline-danger btn-sm"
                  title="Delete"
                  @click="deleteIdentifier(identifier)"
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
      <div class="modal-dialog">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title">
              {{ showEditModal ? 'Edit Identifier' : 'Add Identifier' }}
            </h5>
            <button type="button" class="btn-close" @click="closeModal"></button>
          </div>
          <div class="modal-body">
            <form @submit.prevent="submitForm">
              <div class="mb-3">
                <label class="form-label">Identifier Type <span class="text-danger">*</span></label>
                <select v-model="form.identifier_type" class="form-select" required>
                  <option value="">Select type...</option>
                  <option v-for="(label, value) in identifierTypes" :key="value" :value="value">
                    {{ label }}
                  </option>
                </select>
              </div>
              <div class="mb-3">
                <label class="form-label">Value <span class="text-danger">*</span></label>
                <input
                  v-model="form.value"
                  type="text"
                  class="form-control"
                  :class="{ 'is-invalid': formError }"
                  required
                  placeholder="Enter identifier value"
                />
                <div v-if="formError" class="invalid-feedback">
                  {{ formError }}
                </div>
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
import { ref, computed, onMounted, nextTick, watch } from 'vue'
import $axios from '../utils'
import { showSuccess, showError } from '../alerts'
import { isAxiosError } from 'axios'
import StandardCard from './StandardCard.vue'

// Types
interface ProductIdentifier {
  id: string
  identifier_type: string
  value: string
  created_at: string
}

interface Props {
  productId: string
  hasCrudPermissions?: boolean
  billingPlan?: string
}

const props = withDefaults(defineProps<Props>(), {
  hasCrudPermissions: false,
  billingPlan: 'community'
})

// State
const identifiers = ref<ProductIdentifier[]>([])
const isLoading = ref(false)
const error = ref<string | null>(null)
const showAddModal = ref(false)
const showEditModal = ref(false)
const isSubmitting = ref(false)
const formError = ref('')
const editingIdentifier = ref<ProductIdentifier | null>(null)
const barcodeErrors = ref<Record<string, boolean>>({})

// Form state
const form = ref({
  identifier_type: '',
  value: ''
})

// Identifier types mapping
const identifierTypes = {
  'gtin_12': 'GTIN-12 (UPC-A)',
  'gtin_13': 'GTIN-13 (EAN-13)',
  'gtin_14': 'GTIN-14 / ITF-14',
  'gtin_8': 'GTIN-8',
  'sku': 'SKU',
  'mpn': 'MPN',
  'asin': 'ASIN',
  'gs1_gpc_brick': 'GS1 GPC Brick code',
  'cpe': 'CPE',
  'purl': 'PURL'
}

// Computed
const hasData = computed(() => identifiers.value.length > 0)
const isFeatureAllowed = computed(() => props.billingPlan !== 'community')
const canManageIdentifiers = computed(() => props.hasCrudPermissions && isFeatureAllowed.value)

// Methods
const getIdentifierTypeDisplayName = (type: string): string => {
  return identifierTypes[type as keyof typeof identifierTypes] || type
}

const canRenderBarcode = (type: string): boolean => {
  // Only render barcodes for standard barcode formats (GTIN family)
  const allowedTypes = ['gtin_12', 'gtin_13', 'gtin_14', 'gtin_8']
  return allowedTypes.includes(type)
}

const getBarcodeFormat = (type: string): string => {
  const formatMap: Record<string, string> = {
    'gtin_12': 'UPC',
    'gtin_13': 'EAN13',
    'gtin_14': 'ITF14',
    'gtin_8': 'EAN8'
  }
  return formatMap[type] || 'EAN13'
}

const renderBarcodes = async () => {
  // Wait for Vue to update the DOM completely
  await nextTick()
  await nextTick() // Double nextTick to ensure template is fully rendered

  // Add a small delay to ensure DOM is fully updated
  await new Promise(resolve => setTimeout(resolve, 50))

  // Dynamic import of JsBarcode
  let JsBarcode: (element: Element, text: string, options?: Record<string, unknown>) => void
  try {
    const jsbarcode = await import('jsbarcode')
    JsBarcode = jsbarcode.default || jsbarcode
  } catch (err) {
    console.error('Failed to load JsBarcode library:', err)
    return
  }

  for (const identifier of identifiers.value) {
    if (canRenderBarcode(identifier.identifier_type)) {
      try {
        // Get the SVG element using the data attribute
        const svgElements = document.querySelectorAll(`[data-barcode-id="${identifier.id}"]`)

        if (svgElements.length > 0) {
          const svg = svgElements[0] as SVGElement

          const format = getBarcodeFormat(identifier.identifier_type)

          JsBarcode(svg, identifier.value, {
            format: format,
            width: 2,
            height: 50,
            displayValue: true,
            fontSize: 14,
            fontOptions: 'bold',
            font: 'monospace',
            textMargin: 8,
            textAlign: 'center',
            textPosition: 'bottom',
            margin: 10,
            background: '#ffffff',
            lineColor: '#000000'
          })

          // Clear any previous error for this identifier
          barcodeErrors.value[identifier.id] = false
        }
      } catch (err) {
        console.warn(`Failed to generate barcode for ${identifier.identifier_type}: ${identifier.value}`, err)
        barcodeErrors.value[identifier.id] = true
      }
    }
  }
}



const loadIdentifiers = async () => {
  isLoading.value = true
  error.value = null

    try {
    const response = await $axios.get(`/api/v1/products/${props.productId}/identifiers`)
    identifiers.value = response.data

    // Barcodes will be rendered by the watch function
  } catch (err) {
    console.error('Error loading identifiers:', err)
    error.value = 'Failed to load identifiers'

    if (isAxiosError(err)) {
      showError(err.response?.data?.detail || 'Failed to load identifiers')
    } else {
      showError('Failed to load identifiers')
    }
  } finally {
    isLoading.value = false
  }
}

const resetForm = () => {
  form.value = {
    identifier_type: '',
    value: ''
  }
  formError.value = ''
  editingIdentifier.value = null
}

const closeModal = () => {
  showAddModal.value = false
  showEditModal.value = false
  resetForm()
}

const editIdentifier = (identifier: ProductIdentifier) => {
  editingIdentifier.value = identifier
  form.value = {
    identifier_type: identifier.identifier_type,
    value: identifier.value
  }
  showEditModal.value = true
}

const submitForm = async () => {
  if (!form.value.identifier_type || !form.value.value.trim()) {
    formError.value = 'Both identifier type and value are required'
    return
  }

  isSubmitting.value = true
  formError.value = ''

  try {
    if (showEditModal.value && editingIdentifier.value) {
      // Update existing identifier
      const response = await $axios.put(
        `/api/v1/products/${props.productId}/identifiers/${editingIdentifier.value.id}`,
        {
          identifier_type: form.value.identifier_type,
          value: form.value.value.trim()
        }
      )

      // Update the identifier in the list
      const index = identifiers.value.findIndex(i => i.id === editingIdentifier.value!.id)
      if (index !== -1) {
        identifiers.value[index] = response.data
      }

      showSuccess('Identifier updated successfully!')
    } else {
      // Create new identifier
      const response = await $axios.post(`/api/v1/products/${props.productId}/identifiers`, {
        identifier_type: form.value.identifier_type,
        value: form.value.value.trim()
      })

      identifiers.value.push(response.data)
      showSuccess('Identifier added successfully!')
    }

    closeModal()

    // Re-render barcodes after adding/updating
    await renderBarcodes()
  } catch (err) {
    console.error('Error saving identifier:', err)

    if (isAxiosError(err)) {
      formError.value = err.response?.data?.detail || 'Failed to save identifier'
      showError(err.response?.data?.detail || 'Failed to save identifier')
    } else {
      formError.value = 'Failed to save identifier'
      showError('Failed to save identifier')
    }
  } finally {
    isSubmitting.value = false
  }
}

const deleteIdentifier = async (identifier: ProductIdentifier) => {
  if (!confirm(`Are you sure you want to delete the ${getIdentifierTypeDisplayName(identifier.identifier_type)} identifier "${identifier.value}"?`)) {
    return
  }

  try {
    await $axios.delete(`/api/v1/products/${props.productId}/identifiers/${identifier.id}`)

    // Remove from list
    identifiers.value = identifiers.value.filter(i => i.id !== identifier.id)

    // Clean up barcode error state
    delete barcodeErrors.value[identifier.id]

    showSuccess('Identifier deleted successfully!')
  } catch (err) {
    console.error('Error deleting identifier:', err)

    if (isAxiosError(err)) {
      showError(err.response?.data?.detail || 'Failed to delete identifier')
    } else {
      showError('Failed to delete identifier')
    }
  }
}

// Watch for changes in identifiers to re-render barcodes
watch(identifiers, async (newIdentifiers) => {
  if (newIdentifiers.length > 0) {
    // Add a small delay to ensure the template has updated
    await nextTick()
    await renderBarcodes()
  }
}, { deep: true, flush: 'post' })

// Lifecycle
onMounted(() => {
  loadIdentifiers()
})

// Expose methods for external use
defineExpose({
  loadIdentifiers
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

code {
  font-size: 0.9em;
  background-color: #f8f9fa;
  padding: 0.2rem 0.4rem;
  border-radius: 0.25rem;
}

.barcode-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.25rem;
  width: 100%;
  text-align: center;
}

.barcode-svg {
  border: 1px solid #dee2e6;
  border-radius: 0.25rem;
  background-color: #ffffff;
  max-width: 180px;
  height: auto;
  display: block;
  margin: 0 auto;
}
</style>