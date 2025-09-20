<template>
  <button
    class="copy-btn-pro"
    :class="{ copied: showCopied }"
    title="Copy token to clipboard"
    @click="copyToken"
  >
    <i :class="showCopied ? 'fas fa-check' : 'far fa-copy'"></i>
    <span>{{ showCopied ? 'Copied!' : 'Copy' }}</span>
  </button>
</template>

<script setup lang="ts">
import { ref } from 'vue'

// Type for the window object with our custom functions
interface NotificationMethods {
  showSuccess?: (message: string) => void | Promise<unknown>
  showError?: (message: string) => void | Promise<unknown>
}

const showCopied = ref(false)

function displayCopiedFor2Seconds() {
  showCopied.value = true
  setTimeout(() => {
    showCopied.value = false
  }, 2000)
}

function copyToken() {
  const tokenElement = document.getElementById('access-token')
  if (!tokenElement) {
    console.error('Token element not found')
    return
  }

  const token = tokenElement.innerText || tokenElement.textContent || ''

  navigator.clipboard.writeText(token).then(() => {
    displayCopiedFor2Seconds()

    // Use the proper SweetAlert2 notification system
    const windowWithNotifications = window as NotificationMethods
    if (windowWithNotifications.showSuccess) {
      windowWithNotifications.showSuccess('Token copied to clipboard!')
    }
  }).catch(err => {
    console.error('Failed to copy token:', err)
    // Fallback for older browsers
    fallbackCopyToClipboard(token)
  })
}

function fallbackCopyToClipboard(text: string) {
  const textArea = document.createElement('textarea')
  textArea.value = text
  textArea.style.position = 'fixed'
  textArea.style.left = '-999999px'
  textArea.style.top = '-999999px'
  document.body.appendChild(textArea)
  textArea.focus()
  textArea.select()

  try {
    document.execCommand('copy')
    displayCopiedFor2Seconds()

    // Show success notification for fallback too
    const windowWithNotifications = window as NotificationMethods
    if (windowWithNotifications.showSuccess) {
      windowWithNotifications.showSuccess('Token copied to clipboard!')
    }
  } catch (err) {
    console.error('Fallback copy failed:', err)
    const windowWithNotifications = window as NotificationMethods
    if (windowWithNotifications.showError) {
      windowWithNotifications.showError('Failed to copy token. Please copy manually.')
    }
  }

  document.body.removeChild(textArea)
}
</script>

<style scoped>
.copy-btn-pro {
  background: #ffffff;
  border: 1px solid #d1d5db;
  border-radius: 0.375rem;
  padding: 0.375rem 0.75rem;
  font-size: 0.75rem;
  color: #374151;
  cursor: pointer;
  transition: all 0.2s ease;
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
  font-weight: 500;
  text-decoration: none;
  white-space: nowrap;
}

.copy-btn-pro:hover {
  background: #f9fafb;
  border-color: #9ca3af;
  color: #1f2937;
}

.copy-btn-pro:active {
  background: #f3f4f6;
  transform: scale(0.98);
}

.copy-btn-pro:focus {
  outline: 2px solid #3b82f6;
  outline-offset: 2px;
}

.copy-btn-pro.copied {
  background: #d1fae5;
  border-color: #10b981;
  color: #065f46;
}

.copy-btn-pro i {
  font-size: 0.6875rem;
}

.copy-btn-pro span {
  font-size: 0.75rem;
  line-height: 1;
  font-weight: 500;
}
</style>