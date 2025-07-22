<template>
  <div class="tokens-container">
    <!-- Empty state -->
    <div v-if="tokens.length === 0" class="empty-state">
      <div class="empty-icon">
        <i class="fas fa-key"></i>
      </div>
      <h3 class="empty-title">No personal access tokens</h3>
      <p class="empty-description">
        Generate a personal access token to access the sbomify API from scripts and applications.
      </p>
    </div>

    <!-- Tokens list -->
    <div v-else class="tokens-list">
      <div class="tokens-header">
        <div class="header-cell name-cell">Token</div>
        <div class="header-cell date-cell">Created</div>
        <div class="header-cell actions-cell"></div>
      </div>

      <div v-for="token in tokens" :key="token.id" class="token-row">
        <div class="token-cell name-cell">
          <div class="token-info">
            <div class="token-name">{{ token.description }}</div>
            <div class="token-hint">Personal access token</div>
          </div>
        </div>

        <div class="token-cell date-cell">
          <span class="token-date">{{ formatDate(token.created_at) }}</span>
        </div>

        <div class="token-cell actions-cell">
          <button
            class="delete-btn"
            title="Delete token"
            @click="confirmDelete(token)"
          >
            <i class="fas fa-trash"></i>
          </button>
        </div>
      </div>
    </div>

    <!-- Delete Confirmation Modal -->
    <DeleteConfirmationModal
      v-model:show="showDeleteModal"
      title="Delete personal access token?"
      :message="`Are you sure you want to delete the &quot;${tokenToDelete?.description}&quot; token?`"
      warning-message="This action cannot be undone. Applications using this token will no longer be able to access the sbomify API."
      confirm-text="Delete token"
      @confirm="deleteToken"
      @cancel="cancelDelete"
    />
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import DeleteConfirmationModal from './DeleteConfirmationModal.vue'

interface AccessToken {
  id: string
  description: string
  created_at: string
}

const props = defineProps<{
  tokensDataElementId: string
  csrfToken: string
}>()

const tokens = ref<AccessToken[]>([])
const showDeleteModal = ref(false)
const tokenToDelete = ref<AccessToken | null>(null)

const confirmDelete = (token: AccessToken): void => {
  tokenToDelete.value = token
  showDeleteModal.value = true
}

const cancelDelete = (): void => {
  showDeleteModal.value = false
  tokenToDelete.value = null
}

const deleteToken = (): void => {
  if (!tokenToDelete.value) return

  // Navigate to the delete URL
  window.location.href = `/access_tokens/${tokenToDelete.value.id}/delete`
}

const formatDate = (dateString: string): string => {
  const date = new Date(dateString)
  const now = new Date()
  const diffInDays = Math.floor((now.getTime() - date.getTime()) / (1000 * 60 * 60 * 24))

  if (diffInDays === 0) {
    return 'Today'
  } else if (diffInDays === 1) {
    return 'Yesterday'
  } else if (diffInDays < 7) {
    return `${diffInDays} days ago`
  } else {
    return date.toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric'
    })
  }
}

const loadTokens = (): void => {
  try {
    const element = document.getElementById(props.tokensDataElementId)
    if (element && element.textContent) {
      tokens.value = JSON.parse(element.textContent)
    }
  } catch (error) {
    console.error('Error loading tokens data:', error)
    tokens.value = []
  }
}

// Load tokens when component mounts
loadTokens()
</script>

<style scoped>
.tokens-container {
  min-height: 200px;
}

/* Empty state styles */
.empty-state {
  text-align: center;
  padding: 48px 24px;
  color: #656d76;
}

.empty-icon {
  font-size: 48px;
  color: #d1d5db;
  margin-bottom: 16px;
}

.empty-title {
  font-size: 18px;
  font-weight: 600;
  color: #24292f;
  margin: 0 0 8px 0;
}

.empty-description {
  font-size: 14px;
  line-height: 1.5;
  margin: 0;
  max-width: 400px;
  margin-left: auto;
  margin-right: auto;
}

/* Tokens list styles */
.tokens-list {
  border: 1px solid #e9ecef;
  border-radius: 8px;
  overflow: hidden;
  background: #fff;
}

.tokens-header {
  display: flex;
  background: #f8f9fa;
  border-bottom: 1px solid #e9ecef;
  font-weight: 600;
  font-size: 12px;
  color: #656d76;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.header-cell {
  padding: 12px 16px;
}

.token-row {
  display: flex;
  border-bottom: 1px solid #f1f3f4;
  transition: background-color 0.2s;
}

.token-row:last-child {
  border-bottom: none;
}

.token-row:hover {
  background: #f8f9fa;
}

.token-cell {
  padding: 16px;
  display: flex;
  align-items: center;
}

.name-cell {
  flex: 1;
  min-width: 0; /* Allow flex item to shrink */
}

.date-cell {
  width: 140px;
  flex-shrink: 0;
}

.actions-cell {
  width: 80px;
  flex-shrink: 0;
  justify-content: center;
}

.token-info {
  min-width: 0; /* Allow content to truncate */
}

.token-name {
  font-weight: 600;
  color: #24292f;
  font-size: 14px;
  line-height: 1.4;
  word-break: break-word;
}

.token-hint {
  font-size: 12px;
  color: #656d76;
  margin-top: 2px;
}

.token-date {
  font-size: 13px;
  color: #656d76;
}

.delete-btn {
  background: transparent;
  border: 1px solid transparent;
  border-radius: 6px;
  color: #656d76;
  cursor: pointer;
  padding: 6px 8px;
  font-size: 13px;
  transition: all 0.2s;
  display: flex;
  align-items: center;
  justify-content: center;
}

.delete-btn:hover {
  background: #fef2f2;
  border-color: #fecaca;
  color: #dc2626;
}

.delete-btn:focus {
  outline: 2px solid #dc2626;
  outline-offset: 2px;
}

/* Responsive adjustments */
@media (max-width: 768px) {
  .tokens-header {
    display: none;
  }

  .token-row {
    flex-direction: column;
    padding: 16px;
  }

  .token-cell {
    padding: 4px 0;
    width: 100%;
  }

  .token-cell.actions-cell {
    justify-content: flex-start;
    margin-top: 8px;
  }

  .date-cell::before {
    content: "Created ";
    font-weight: 600;
    color: #24292f;
  }
}
</style>