<template>
  <div class="public-status-container" :class="{ 'inline-mode': isInlineMode }">
    <div class="public-status-widget" :class="{ 'inline-widget': isInlineMode }">
      <!-- Floating widget mode (original) -->
      <template v-if="!isInlineMode">
        <div class="status-row">
          <div class="status-badge-container">
            <span v-if="isPublic" class="status-badge public-badge">
              <i class="fas fa-globe"></i>
              <span>Public</span>
              <small v-if="itemType === 'release'" class="inheritance-note d-block">(inherited from product)</small>
            </span>
            <span v-else class="status-badge private-badge">
              <i class="fas fa-lock"></i>
              <span>Private</span>
              <small v-if="itemType === 'release'" class="inheritance-note d-block">(inherited from product)</small>
            </span>
          </div>

          <div class="toggle-container">
            <div class="toggle-switch" :class="{ loading: isLoading }">
              <input
                id="togglePublicStatus"
                class="toggle-input"
                type="checkbox"
                :checked="isPublic"
                :disabled="isLoading"
                @click.prevent="togglePublicStatus()"
              />
              <label for="togglePublicStatus" class="toggle-slider">
                <span class="toggle-handle"></span>
              </label>
              <div v-if="isLoading" class="loading-spinner">
                <i class="fas fa-spinner fa-spin"></i>
              </div>
            </div>
          </div>
        </div>

        <div v-if="isPublic" class="copy-row">
          <div class="copy-button-wrapper" @click="copyToClipboard">
            <i class="fas fa-copy"></i>
            <span>Copy public URL</span>
          </div>
        </div>
      </template>

      <!-- Inline mode (integrated with header) -->
      <template v-else>
        <div class="inline-status-controls">
          <div class="status-indicator" :class="{ 'public': isPublic, 'private': !isPublic }">
            <i :class="isPublic ? 'fas fa-globe' : 'fas fa-lock'"></i>
            <span class="status-text">{{ isPublic ? 'Public' : 'Private' }}</span>
            <span v-if="itemType === 'release'" class="inheritance-note">(inherited from product)</span>
          </div>

          <div class="toggle-switch" :class="{ loading: isLoading }">
            <input
              :id="`toggle-${itemId}`"
              class="toggle-input"
              type="checkbox"
              :checked="isPublic"
              :disabled="isLoading"
              @click.prevent="togglePublicStatus()"
            />
            <label :for="`toggle-${itemId}`" class="toggle-slider">
              <span class="toggle-handle"></span>
            </label>
            <div v-if="isLoading" class="loading-spinner">
              <i class="fas fa-spinner fa-spin"></i>
            </div>
          </div>

          <button v-if="isPublic"
                  class="copy-url-btn"
                  title="Copy public URL"
                  @click="copyToClipboard">
            <i class="fas fa-copy"></i>
            <span class="copy-text">Copy URL</span>
          </button>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
  import { ref, onMounted } from 'vue'
  import $axios from '../../../core/js/utils'
  import { showSuccess, showError } from '../../../core/js/alerts'

  interface Props {
    itemType: string
    itemId: string
    publicUrl: string
    inline?: string | boolean
  }

  interface ApiErrorResponse {
    response?: {
      status: number
      data?: {
        detail?: string
      }
    }
  }

  const props = defineProps<Props>()

  const isPublic = ref(false)
  const isLoading = ref(false)

  // Convert string "true"/"false" to boolean for inline prop
  const isInlineMode = props.inline === true || props.inline === 'true'

  // Use the proper core API endpoints that have constraint validation
  const getApiUrl = () => {
    switch (props.itemType) {
      case 'product':
        return `/api/v1/products/${props.itemId}`
      case 'project':
        return `/api/v1/projects/${props.itemId}`
      case 'component':
        return `/api/v1/components/${props.itemId}`
      case 'release':
        // Releases inherit public status from their parent product
        // Extract product ID from the public URL: /public/product/{product_id}/release/{release_id}/
        const urlMatch = props.publicUrl.match(/\/public\/product\/([^/]+)\/release\//)
        if (!urlMatch) {
          throw new Error('Could not extract product ID from release public URL')
        }
        const productId = urlMatch[1]
        return `/api/v1/products/${productId}`
      default:
        throw new Error(`Unknown item type: ${props.itemType}`)
    }
  }

  onMounted(async () => {
    try {
      const response = await $axios.get(getApiUrl())
      if (response.status < 200 || response.status >= 300) {
        throw new Error('Network response was not ok. ' + response.statusText)
      }
      isPublic.value = response.data.is_public
    } catch (error) {
      console.error('Failed to load public status:', error)
      showError('Failed to load public status')
    }
  })

  const togglePublicStatus = async () => {
    const previousState = isPublic.value
    const newPublicStatus = !isPublic.value

    // Optimistically update the UI
    isPublic.value = newPublicStatus
    isLoading.value = true

    const data = {
      is_public: newPublicStatus,
    }

    try {
      const response = await $axios.patch(getApiUrl(), data)

      if (response.status < 200 || response.status >= 300) {
        throw new Error('Network response was not ok. ' + response.statusText)
      }

      // Update with the actual response from server (should match our optimistic update)
      isPublic.value = response.data.is_public

      // Show success message
      if (props.itemType === 'release') {
        // For releases, we're actually updating the parent product
        if (isPublic.value) {
          showSuccess('Release product is now public (release inherits this status)')
        } else {
          showSuccess('Release product is now private (release inherits this status)')
        }
      } else {
        if (isPublic.value) {
          showSuccess(
            `${props.itemType.charAt(0).toUpperCase() + props.itemType.slice(1)} is now public`
          )
        } else {
          showSuccess(
            `${props.itemType.charAt(0).toUpperCase() + props.itemType.slice(1)} is now private`
          )
        }
      }
    } catch (error) {
      const apiError = error as ApiErrorResponse
      console.error('Failed to toggle public status:', error)

      // Revert to previous state on error
      isPublic.value = previousState

      // Handle specific error cases
      if (apiError.response?.status === 403) {
        const errorMessage = apiError.response.data?.detail || 'Permission denied'
        showError(errorMessage)
      } else if (apiError.response?.status === 400) {
        const errorMessage = apiError.response.data?.detail || 'Invalid request'
        showError(errorMessage)
      } else {
        showError('Failed to update public status. Please try again.')
      }
    } finally {
      isLoading.value = false
    }
  }

  const copyToClipboard = async () => {
    try {
      await navigator.clipboard.writeText(props.publicUrl)
      showSuccess('Public URL copied to clipboard')
    } catch (error) {
      console.error('Failed to copy to clipboard:', error)
      showError('Failed to copy URL to clipboard')
    }
  }
</script>

<style scoped>
  /* Container positioning */
  .public-status-container {
    position: absolute;
    top: 1rem;
    right: 1rem;
    z-index: 1000;
  }

  /* Inline mode */
  .public-status-container.inline-mode {
    position: static;
    display: inline-flex;
    align-items: center;
    z-index: auto;
  }

  /* Main widget */
  .public-status-widget {
    background: rgba(255, 255, 255, 0.95);
    backdrop-filter: blur(10px);
    border: 1px solid rgba(255, 255, 255, 0.2);
    border-radius: 8px;
    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.1);
    padding: 0.75rem;
    min-width: 200px;
    transition: all 0.2s ease;
  }

  .public-status-widget.inline-widget {
    background: transparent;
    backdrop-filter: none;
    border: none;
    border-radius: 0;
    box-shadow: none;
    padding: 0;
    min-width: auto;
    display: inline-flex;
    align-items: center;
  }

  /* Inline status controls - the main container for inline mode */
  .inline-status-controls {
    display: flex;
    align-items: center;
    gap: 1rem;
    padding: 0.5rem 1rem;
    background: linear-gradient(135deg, #f8fafc, #f1f5f9);
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
    transition: all 0.2s ease;
  }

  .inline-status-controls:hover {
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
    transform: translateY(-1px);
  }

  .public-status-widget:hover {
    box-shadow: 0 6px 25px rgba(0, 0, 0, 0.15);
    transform: translateY(-1px);
  }

  /* Status row - badge and toggle */
  .status-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.75rem;
  }

  /* Status indicator in inline mode */
  .status-indicator {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-size: 0.875rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.025em;
  }

  .status-indicator.public {
    color: #10b981;
  }

  .status-indicator.public i {
    color: #10b981;
  }

  .status-indicator.private {
    color: #6b7280;
  }

  .status-indicator.private i {
    color: #6b7280;
  }

  .status-text {
    font-size: 0.75rem;
  }

  .inheritance-note {
    font-size: 0.7rem;
    color: #9ca3af;
    font-style: italic;
    margin-left: 0.25rem;
  }

  .status-badge-container {
    flex: 1;
  }

  .status-badge {
    display: inline-flex;
    align-items: center;
    gap: 0.375rem;
    padding: 0.25rem 0.5rem;
    border-radius: 4px;
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.025em;
  }

  .public-badge {
    background: rgba(16, 185, 129, 0.1);
    color: #065f46;
    border: 1px solid rgba(16, 185, 129, 0.2);
  }

  .private-badge {
    background: rgba(107, 114, 128, 0.1);
    color: #374151;
    border: 1px solid rgba(107, 114, 128, 0.2);
  }

  .status-badge i {
    font-size: 0.7rem;
  }

  /* Toggle switch */
  .toggle-container {
    position: relative;
  }

  .toggle-switch {
    position: relative;
    display: inline-block;
  }



  .toggle-input {
    opacity: 0;
    width: 0;
    height: 0;
    position: absolute;
  }

  .toggle-slider {
    position: relative;
    display: block;
    width: 44px;
    height: 24px;
    background: #e5e7eb;
    border-radius: 12px;
    cursor: pointer;
    transition: all 0.3s ease;
    border: 2px solid transparent;
  }

  .toggle-slider:hover {
    background: #d1d5db;
  }

  .toggle-handle {
    position: absolute;
    top: 2px;
    left: 2px;
    width: 16px;
    height: 16px;
    background: white;
    border-radius: 50%;
    transition: all 0.3s ease;
    box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
  }

  .toggle-input:checked + .toggle-slider {
    background: #10b981;
    border-color: #10b981;
  }

  .toggle-input:checked + .toggle-slider .toggle-handle {
    transform: translateX(20px);
    background: white;
  }

  .toggle-input:disabled + .toggle-slider {
    opacity: 0.6;
    cursor: not-allowed;
  }

  .toggle-input:focus + .toggle-slider {
    box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
  }

  /* Loading state */
  .toggle-switch.loading .toggle-slider {
    opacity: 0.7;
  }

  .loading-spinner {
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    color: #6b7280;
    font-size: 0.75rem;
    pointer-events: none;
  }

  /* Copy button row */
  .copy-row {
    margin-top: 0.75rem;
    padding-top: 0.75rem;
    border-top: 1px solid rgba(229, 231, 235, 0.5);
  }

  .copy-button-wrapper {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 0.5rem;
    padding: 0.5rem 0.75rem;
    background: linear-gradient(135deg, #3b82f6, #1d4ed8);
    color: white;
    border-radius: 6px;
    cursor: pointer;
    font-size: 0.75rem;
    font-weight: 500;
    text-align: center;
    transition: all 0.2s ease;
    box-shadow: 0 2px 4px rgba(59, 130, 246, 0.2);
  }

  .copy-button-wrapper:hover {
    background: linear-gradient(135deg, #1d4ed8, #1e40af);
    transform: translateY(-1px);
    box-shadow: 0 4px 8px rgba(59, 130, 246, 0.3);
  }

  .copy-button-wrapper:active {
    transform: translateY(0);
    box-shadow: 0 2px 4px rgba(59, 130, 246, 0.2);
  }

  /* Copy URL button in inline mode */
  .copy-url-btn {
    display: flex;
    align-items: center;
    gap: 0.375rem;
    padding: 0.375rem 0.75rem;
    background: linear-gradient(135deg, #3b82f6, #1d4ed8);
    color: white;
    border: none;
    border-radius: 6px;
    font-size: 0.75rem;
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.025em;
    cursor: pointer;
    transition: all 0.2s ease;
    box-shadow: 0 2px 4px rgba(59, 130, 246, 0.2);
  }

  .copy-url-btn:hover {
    background: linear-gradient(135deg, #1d4ed8, #1e40af);
    transform: translateY(-1px);
    box-shadow: 0 4px 8px rgba(59, 130, 246, 0.3);
  }

  .copy-url-btn:active {
    transform: translateY(0);
    box-shadow: 0 2px 4px rgba(59, 130, 246, 0.2);
  }

  .copy-text {
    font-size: 0.75rem;
  }

  /* Responsive design */
  @media (max-width: 768px) {
    .public-status-container {
      position: static;
      margin-bottom: 1rem;
      width: 100%;
    }

    .public-status-widget {
      min-width: unset;
      width: 100%;
    }

    .status-row {
      flex-direction: column;
      align-items: stretch;
      gap: 0.5rem;
    }

    .status-badge-container {
      text-align: center;
    }

    .toggle-container {
      display: flex;
      justify-content: center;
    }
  }

  /* Accessibility improvements */
  @media (prefers-reduced-motion: reduce) {
    .public-status-widget,
    .toggle-slider,
    .toggle-handle,
    .copy-button-wrapper {
      transition: none;
    }

    .public-status-widget:hover,
    .copy-button-wrapper:hover {
      transform: none;
    }
  }

  /* High contrast mode support */
  @media (prefers-contrast: high) {
    .public-status-widget {
      border: 2px solid #000;
      background: #fff;
    }

    .toggle-slider {
      border: 2px solid #000;
    }

    .public-badge,
    .private-badge {
      border: 2px solid currentColor;
    }
  }
</style>
