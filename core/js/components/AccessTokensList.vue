<template>
  <div>
    <div v-if="tokens.length === 0" class="no-items">
      No tokens added
    </div>
    <table v-else class="table">
      <thead>
        <tr>
          <th>Description</th>
          <th>Created at</th>
          <th scope="col" class="text-center actions-header">Actions</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="token in tokens" :key="token.id">
          <td>{{ token.description }}</td>
          <td>{{ formatDate(token.created_at) }}</td>
          <td class="border-left">
            <div class="actions">
              <button
                class="btn btn-sm btn-danger"
                title="Delete Access Token"
                @click="confirmDelete(token)"
              >
                <i class="fas fa-trash"></i>
              </button>
            </div>
          </td>
        </tr>
      </tbody>
    </table>

    <!-- Delete Confirmation Modal -->
    <DeleteConfirmationModal
      v-model:show="showDeleteModal"
      title="Delete Access Token"
      message="Are you sure you want to delete the access token"
      :item-name="tokenToDelete?.description"
      warning-message="This action cannot be undone and will permanently remove the access token."
      confirm-text="Delete Token"
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
  return new Date(dateString).toLocaleString()
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
.no-items {
  padding: 1rem 0;
  color: #6c757d;
}

.actions {
  display: flex;
  justify-content: center;
  gap: 0.5rem;
}

.btn-sm {
  padding: 0.25rem 0.5rem;
  font-size: 0.875rem;
}

.actions-header {
  width: 100px;
}
</style>