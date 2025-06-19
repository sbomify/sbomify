<template>
  <div class="licenses-editor">
    <!-- License Tags/Bubbles Display -->
    <div v-if="licenseTags.length > 0" class="license-tags-container">
      <div
        v-for="(tag, index) in licenseTags"
        :key="`tag-${index}`"
        class="license-tag"
        :class="{ 'invalid': tag.isInvalid }"
      >
        <span class="license-tag-text">{{ tag.value }}</span>
        <button
          type="button"
          class="license-tag-remove"
          title="Remove license"
          @click="removeTag(index)"
        >
          <span aria-hidden="true">&times;</span>
        </button>
      </div>
    </div>

    <div class="license-expression-input">
      <div class="license-input-container">
        <div class="input-with-button">
          <input
            ref="licenseInputRef"
            v-model="licenseExpression"
            type="text"
            class="form-control"
            :class="{ 'is-invalid': validationError }"
            placeholder="Enter license expression (e.g., 'MIT' or 'Apache-2.0 WITH Commons-Clause')"
            @input="onInput"
            @keydown="handleKeyDown"
            @focus="showSuggestions = true"
            @blur="handleBlur"
          >
          <button
            type="button"
            class="btn btn-primary add-license-btn"
            :disabled="!licenseExpression.trim()"
            title="Add license as tag"
            @click="addCurrentExpression"
          >
            Add
          </button>
        </div>
        <div v-if="showSuggestions && filteredLicenses.length > 0" class="license-suggestions">
          <div
            v-for="(license, index) in filteredLicenses"
            :key="license.key"
            class="license-suggestion"
            :class="{ 'active': index === selectedIndex }"
            @mousedown.prevent="selectLicense(license)"
          >
            <div class="license-name">{{ license.name }}</div>
            <div class="license-key">{{ license.key }}</div>
            <div v-if="license.category" class="license-category" :class="{ 'operator': license.category === 'operator' }">{{ license.category }}</div>
          </div>
        </div>
      </div>
      <div v-if="validationError" class="invalid-feedback">
        {{ validationError }}
      </div>
    </div>

    <!-- Custom License Form -->
    <div v-if="unknownTokens.length > 0" class="custom-license-form">
      <div class="alert alert-info">
        <h5>Unknown License Detected</h5>
        <p>The following license identifier is not recognized: <span class="badge">{{ unknownTokens[0] }}</span></p>
        <p>Please provide additional information to register this custom license.</p>
      </div>
      <div class="card">
        <div class="card-header">
          <h6>Register Custom License: {{ unknownTokens[0] }}</h6>
        </div>
        <div class="card-body">
          <form @submit.prevent="submitCustomLicense">
            <div class="row">
              <div class="col-md-6">
                <div class="form-group">
                  <label class="form-label">License Name <span class="text-danger">*</span></label>
                  <input
                    v-model="customLicense.name"
                    type="text"
                    class="form-control"
                    :class="{ 'is-invalid': validationErrors?.name }"
                    placeholder="Enter license name"
                    required
                  >
                  <div v-if="validationErrors?.name" class="invalid-feedback">
                    {{ validationErrors.name }}
                  </div>
                </div>
              </div>
              <div class="col-md-6">
                <div class="form-group">
                  <label class="form-label">License URL</label>
                  <input
                    v-model="customLicense.url"
                    type="url"
                    class="form-control"
                    :class="{ 'is-invalid': validationErrors?.url }"
                    placeholder="https://example.com/license"
                  >
                  <div v-if="validationErrors?.url" class="invalid-feedback">
                    {{ validationErrors.url }}
                  </div>
                </div>
              </div>
            </div>
            <div class="form-group mt-3">
              <label class="form-label">License Text</label>
              <textarea
                v-model="customLicense.text"
                class="form-control"
                :class="{ 'is-invalid': validationErrors?.text }"
                rows="4"
                placeholder="Enter the full text of the license"
              ></textarea>
              <div v-if="validationErrors?.text" class="invalid-feedback">
                {{ validationErrors.text }}
              </div>
            </div>
            <div class="mt-3">
              <button type="submit" class="btn btn-primary" :disabled="!customLicense.name">
                Save License Information
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>

    <!-- Success Message -->
    <div v-if="showCustomLicenseSuccess" class="alert alert-success mt-3">
      Custom license information saved successfully!
    </div>

    <!-- General validation errors from props -->
    <div v-if="validationErrors.general" class="invalid-feedback d-block mt-2">
      {{ validationErrors.general }}
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, watch, onMounted, nextTick, onBeforeUnmount } from 'vue'
import type { CustomLicense } from '../type_defs'
import $axios from '../../../core/js/utils'
import { AxiosError } from 'axios'

interface LicenseInfo {
  key: string;
  name: string;
  category?: string | null; // Make category optional since SPDX licenses don't have it
  origin: string;
  url?: string;
}

interface ValidationResponse {
  status: number;
  normalized?: string;
  tokens?: Array<{ key: string; known: boolean }>;
  unknown_tokens?: string[];
  error?: string;
}

interface LicenseTag {
  value: string;
  isInvalid?: boolean;
}

interface Props {
  modelValue: (string | CustomLicense)[]
  validationErrors?: Record<string, string>
  validationResponse: ValidationResponse
}

const props = defineProps<Props>()
const emit = defineEmits(['update:modelValue'])

const licenseExpression = ref('')
const validationError = ref('')
const showCustomLicenseSuccess = ref(false)
const validationErrors = ref<Record<string, string>>(props.validationErrors || {})
const licenseTags = ref<LicenseTag[]>([])

const unknownTokens = computed(() => props.validationResponse?.unknown_tokens || [])

const customLicense = reactive({
  key: '',
  name: '',
  url: '',
  text: '',
})

// --- Autocomplete logic ---
const licenses = ref<LicenseInfo[]>([])
const showSuggestions = ref(false)
const selectedIndex = ref(-1)
const licenseInputRef = ref<HTMLInputElement | null>(null)

const filteredLicenses = computed(() => {
  if (!licenseExpression.value) return licenses.value

  // Get the current cursor position and extract the current token being typed
  const input = licenseInputRef.value
  const cursorPos = input?.selectionStart || licenseExpression.value.length
  const beforeCursor = licenseExpression.value.substring(0, cursorPos)

  // Split by license operators to find the current token
  const operators = ['AND', 'OR', 'WITH']
  const operatorPattern = new RegExp(`\\s+(${operators.join('|')})\\s+`, 'gi')

  // Find the last complete token before cursor
  let currentToken = beforeCursor
  let match
  let lastOperatorEnd = 0

  // Reset the regex lastIndex to avoid issues
  operatorPattern.lastIndex = 0
  while ((match = operatorPattern.exec(beforeCursor)) !== null) {
    lastOperatorEnd = match.index + match[0].length
  }

  if (lastOperatorEnd > 0) {
    currentToken = beforeCursor.substring(lastOperatorEnd).trim()
  }

  // Filter licenses based on the current token being typed
  if (!currentToken) return licenses.value

  const searchTerm = currentToken.toLowerCase().replace(/\s+/g, '-')

  // Create a combined list of licenses and operators
  const combinedSuggestions = [...licenses.value]

  // Add operator suggestions if we have a previous license token
  if (lastOperatorEnd > 0 || (beforeCursor.trim().length > 0 && !currentToken.includes(' '))) {
    // Check if currentToken could be the start of an operator
    const matchingOperators = operators.filter(op =>
      op.toLowerCase().startsWith(currentToken.toLowerCase())
    )

    matchingOperators.forEach(op => {
      combinedSuggestions.push({
        key: op,
        name: `${op} operator`,
        category: 'operator',
        origin: 'system'
      } as LicenseInfo)
    })
  }

  return combinedSuggestions.filter(item => {
    if (item.category === 'operator') {
      return item.key.toLowerCase().startsWith(currentToken.toLowerCase())
    } else {
      const licenseKey = item.key.toLowerCase()
      const licenseName = item.name.toLowerCase()
      return (
        licenseKey.includes(searchTerm) ||
        licenseName.includes(searchTerm)
      )
    }
  })
})

async function loadLicenses() {
  try {
    const response = await $axios.get('/api/v1/licensing/licenses')
    licenses.value = response.data
  } catch {
    // fail silently
  }
}
onMounted(loadLicenses)

// Initialize tags from props
if (props.modelValue && props.modelValue.length > 0) {
  licenseTags.value = props.modelValue.map(lic => ({
    value: typeof lic === 'string' ? lic : (lic.name || ''),
    isInvalid: false
  })).filter(tag => tag.value.length > 0)
  licenseExpression.value = ''
} else {
  licenseTags.value = []
  licenseExpression.value = ''
}

function onInput() {
  showSuggestions.value = true
}

function addCurrentExpression() {
  const expression = licenseExpression.value.trim()
  if (expression && !licenseTags.value.some(tag => tag.value === expression)) {
    licenseTags.value.push({ value: expression })
    licenseExpression.value = ''
    updateModelValue()
    validateTag(expression, licenseTags.value.length - 1)
  }
}

function removeTag(index: number) {
  licenseTags.value.splice(index, 1)
  updateModelValue()
}

function updateModelValue() {
  const allLicenses: string[] = []

  // Add all tags
  licenseTags.value.forEach(tag => {
    allLicenses.push(tag.value)
  })

  // Add current input if it has content
  if (licenseExpression.value.trim()) {
    allLicenses.push(licenseExpression.value.trim())
  }

  emit('update:modelValue', allLicenses)
}

async function validateTag(tagValue: string, tagIndex: number) {
  try {
    const response = await $axios.post('/api/v1/licensing/license-expressions/validate', {
      expression: tagValue
    })

    if (response.data.status === 200) {
      // Valid license - remove invalid flag if it exists
      if (licenseTags.value[tagIndex]) {
        licenseTags.value[tagIndex].isInvalid = false
      }
    } else {
      // Invalid license - mark as invalid
      if (licenseTags.value[tagIndex]) {
        licenseTags.value[tagIndex].isInvalid = true
      }
    }
  } catch {
    // Error during validation - mark as invalid
    if (licenseTags.value[tagIndex]) {
      licenseTags.value[tagIndex].isInvalid = true
    }
  }
}

function handleKeyDown(e: KeyboardEvent) {
  // Handle Backspace on empty input to remove last tag
  if (e.key === 'Backspace' && !licenseExpression.value && licenseTags.value.length > 0) {
    removeTag(licenseTags.value.length - 1)
    return
  }

  // Handle Enter to add current expression as tag (when not using autocomplete)
  if (e.key === 'Enter' && (!showSuggestions.value || selectedIndex.value < 0)) {
    e.preventDefault()
    addCurrentExpression()
    return
  }

  // Autocomplete handling
  if (!showSuggestions.value || filteredLicenses.value.length === 0) return
  if (e.key === 'ArrowDown') {
    e.preventDefault()
    selectedIndex.value = (selectedIndex.value + 1) % filteredLicenses.value.length
  } else if (e.key === 'ArrowUp') {
    e.preventDefault()
    selectedIndex.value = selectedIndex.value <= 0 ? filteredLicenses.value.length - 1 : selectedIndex.value - 1
  } else if (e.key === 'Enter') {
    if (selectedIndex.value >= 0) {
      selectLicense(filteredLicenses.value[selectedIndex.value])
      e.preventDefault()
    }
  } else if (e.key === 'Escape') {
    showSuggestions.value = false
    selectedIndex.value = -1
  }
}

function handleBlur() {
  setTimeout(() => {
    showSuggestions.value = false
    selectedIndex.value = -1
  }, 200)
}

function selectLicense(license: LicenseInfo) {
  // Get current cursor position and replace only the current token
  const input = licenseInputRef.value
  if (!input) {
    // Fallback for when input ref is not available (like in tests)
    if (license.category === 'operator') {
      licenseExpression.value = licenseExpression.value.trim() + ' ' + license.key + ' '
    } else {
      licenseExpression.value = license.key
    }
    showSuggestions.value = false
    selectedIndex.value = -1
    return
  }

  const cursorPos = input.selectionStart || licenseExpression.value.length
  const beforeCursor = licenseExpression.value.substring(0, cursorPos)
  const afterCursor = licenseExpression.value.substring(cursorPos)

  // Find where the current token starts
  const operators = ['AND', 'OR', 'WITH']
  const operatorPattern = new RegExp(`\\s+(${operators.join('|')})\\s+`, 'gi')

  let tokenStart = 0
  let match
  operatorPattern.lastIndex = 0
  while ((match = operatorPattern.exec(beforeCursor)) !== null) {
    tokenStart = match.index + match[0].length
  }

  // Replace only the current token with the selected license/operator
  const beforeToken = licenseExpression.value.substring(0, tokenStart)
  let replacement = license.key

  // If it's an operator, add appropriate spacing
  if (license.category === 'operator') {
    const needsSpaceBefore = beforeToken.length > 0 && !beforeToken.endsWith(' ')
    const needsSpaceAfter = afterCursor.length > 0 && !afterCursor.startsWith(' ')

    replacement = (needsSpaceBefore ? ' ' : '') + license.key + (needsSpaceAfter ? ' ' : '')
  }

  const newExpression = beforeToken + replacement + afterCursor

  licenseExpression.value = newExpression
  showSuggestions.value = false
  selectedIndex.value = -1

  // Position cursor after the inserted license/operator
  nextTick(() => {
    const newCursorPos = tokenStart + replacement.length
    input.setSelectionRange(newCursorPos, newCursorPos)
    input.focus()
  })
}
// --- End autocomplete logic ---

// Watch for changes to validationErrors prop
watch(() => props.validationErrors, (newErrors) => {
  validationErrors.value = newErrors || {}
}, { immediate: true })

// Watch for unknown tokens and update the custom license form
watch(
  () => unknownTokens.value,
  (tokens) => {
    if (tokens.length) {
      customLicense.key = tokens[0]
      customLicense.name = ''
      customLicense.url = ''
      customLicense.text = ''
      // Only clear validation errors if they're not from props
      if (!props.validationErrors) {
        validationErrors.value = {}
      }
    }
  },
  { immediate: true }
)

// Watch for changes in modelValue from parent
watch(() => props.modelValue, (newValue) => {
  if (!newValue || newValue.length === 0) {
    licenseTags.value = []
    licenseExpression.value = ''
  } else {
    const newTags = newValue.map(lic => ({
      value: typeof lic === 'string' ? lic : (lic.name || ''),
      isInvalid: false
    })).filter(tag => tag.value.length > 0)

    // Only update if different to avoid infinite loops
    const currentTagValues = licenseTags.value.map(tag => tag.value).join(',')
    const newTagValues = newTags.map(tag => tag.value).join(',')

    if (currentTagValues !== newTagValues) {
      licenseTags.value = newTags
      licenseExpression.value = ''
    }
  }
})

// Watch licenseExpression for validation (without debouncing, just for validation display)
let debounceTimer: number | null = null
watch(licenseExpression, async (expr) => {
  // Clear any pending debounce
  if (debounceTimer) {
    clearTimeout(debounceTimer)
  }

  if (!expr.trim()) {
    validationError.value = ''
    return
  }

  // Debounce the validation for UI feedback only
  debounceTimer = window.setTimeout(async () => {
    try {
      await $axios.post('/api/v1/licensing/license-expressions/validate', {
        expression: expr
      })
      validationError.value = ''
    } catch (error) {
      if (error instanceof AxiosError) {
        validationError.value = error.response?.data?.detail || 'Invalid license expression'
      } else {
        validationError.value = 'Invalid license expression'
      }
    }
  }, 300) // 300ms debounce
})

// Initialize tags from props
if (props.modelValue && props.modelValue.length > 0) {
  licenseTags.value = props.modelValue.map(lic => ({
    value: typeof lic === 'string' ? lic : (lic.name || ''),
    isInvalid: false
  })).filter(tag => tag.value.length > 0)
  licenseExpression.value = ''
} else {
  licenseTags.value = []
  licenseExpression.value = ''
}

// Clean up timer on component unmount
onBeforeUnmount(() => {
  if (debounceTimer) {
    clearTimeout(debounceTimer)
  }
})

async function validateExpression() {
  try {
    const response = await $axios.post('/api/v1/licensing/license-expressions/validate', {
      expression: licenseExpression.value
    })
    validationError.value = ''
    return response.data
  } catch (error) {
    if (error instanceof AxiosError) {
      validationError.value = error.response?.data?.detail || 'Invalid license expression'
    } else {
      validationError.value = 'Invalid license expression'
    }
    return null
  }
}

async function submitCustomLicense() {
  try {
    // Only clear validation errors if they're not from props
    if (!props.validationErrors) {
      validationErrors.value = {}
    }
    await $axios.post('/api/v1/licensing/custom-licenses', {
      key: customLicense.key,
      name: customLicense.name,
      url: customLicense.url,
      text: customLicense.text,
    })
    showCustomLicenseSuccess.value = true
    setTimeout(() => {
      showCustomLicenseSuccess.value = false
    }, 3000)
    // Revalidate the expression to update the unknown tokens
    await validateExpression()
  } catch (error) {
    if (error instanceof AxiosError && error.response?.data?.detail) {
      validationErrors.value = error.response.data.detail
    } else {
      validationErrors.value = { general: 'Failed to save custom license information' }
    }
  }
}
</script>

<style scoped>
.licenses-editor {
  width: 100%;
}

.license-tags-container {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin-bottom: 0.75rem;
  padding: 0.5rem;
  border: 1px solid #dee2e6;
  border-radius: 0.25rem;
  background-color: #f8f9fa;
  min-height: 2.5rem;
  align-items: flex-start;
  align-content: flex-start;
}

.license-tag {
  display: inline-flex;
  align-items: center;
  background-color: #0d6efd;
  color: white;
  padding: 0.25rem 0.5rem;
  border-radius: 1rem;
  font-size: 0.875rem;
  font-weight: 500;
  gap: 0.5rem;
  max-width: 200px;
  transition: all 0.2s ease;
}

.license-tag.invalid {
  background-color: #dc3545;
}

.license-tag:hover {
  background-color: #0b5ed7;
  transform: translateY(-1px);
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
}

.license-tag.invalid:hover {
  background-color: #bb2d3b;
}

.license-tag-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
  min-width: 0;
}

.license-tag-remove {
  background: none;
  border: none;
  color: white;
  font-size: 1.25rem;
  font-weight: 700;
  line-height: 1;
  cursor: pointer;
  padding: 0;
  width: 1.5rem;
  height: 1.5rem;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  transition: background-color 0.2s ease;
}

.license-tag-remove:hover {
  background-color: rgba(255, 255, 255, 0.2);
}

.license-tag-remove:focus {
  outline: 2px solid rgba(255, 255, 255, 0.5);
  outline-offset: 1px;
}

.license-input-container {
  position: relative;
}

.input-with-button {
  display: flex;
  gap: 0.5rem;
  align-items: flex-start;
}

.input-with-button .form-control {
  flex: 1;
}

.add-license-btn {
  white-space: nowrap;
  padding: 0.375rem 0.75rem;
  font-size: 0.875rem;
  border-radius: 0.25rem;
  flex-shrink: 0;
}

.license-suggestions {
  position: absolute;
  top: 100%;
  left: 0;
  right: 0;
  z-index: 1000;
  max-height: 300px;
  overflow-y: auto;
  background-color: white;
  border: 1px solid #dee2e6;
  border-radius: 0.25rem;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
}
.license-suggestion {
  padding: 0.75rem 1rem;
  cursor: pointer;
  border-bottom: 1px solid #f8f9fa;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}
.license-suggestion:last-child {
  border-bottom: none;
}
.license-suggestion:hover,
.license-suggestion.active {
  background-color: #f8f9fa;
}
.license-suggestion .license-name {
  font-weight: 500;
  color: #212529;
}
.license-suggestion .license-key {
  font-size: 0.875rem;
  color: #6c757d;
  font-family: monospace;
}
.license-suggestion .license-category {
  font-size: 0.75rem;
  color: #6c757d;
  text-transform: capitalize;
  background-color: #e9ecef;
  padding: 0.125rem 0.375rem;
  border-radius: 0.25rem;
  display: inline-block;
}
.license-suggestion .license-category.operator {
  background-color: #d1ecf1;
  color: #0c5460;
  font-weight: 500;
}
.custom-license-form {
  margin-top: 1.5rem;
}
.alert {
  margin-bottom: 1rem;
}
.card {
  background-color: #fff;
  border: 1px solid #dee2e6;
  border-radius: 0.25rem;
  padding: 1.25rem;
}
.form-group {
  margin-bottom: 1rem;
}
.form-label {
  font-weight: 500;
  color: #495057;
  margin-bottom: 0.5rem;
  display: block;
}
.text-danger {
  color: #dc3545;
}
.badge {
  padding: 0.25em 0.5em;
  font-size: 0.875em;
  font-weight: 700;
  color: #fff;
  background-color: #0dcaf0;
  border-radius: 0.25rem;
}
.btn-primary {
  background-color: #0d6efd;
  border-color: #0d6efd;
  color: #fff;
}
.btn-primary:hover {
  background-color: #0b5ed7;
  border-color: #0a58ca;
}
.btn-primary:focus {
  box-shadow: 0 0 0 0.2rem rgba(0, 123, 255, 0.5);
}
.btn-primary:disabled {
  background-color: #0b5ed7;
  border-color: #0a58ca;
  opacity: 0.75;
  cursor: not-allowed;
}
.alert-info {
  background-color: #cff4fc;
  border-color: #b6effb;
  color: #055160;
}
.alert-success {
  background-color: #d1e7dd;
  border-color: #badbcc;
  color: #0f5132;
}
</style>