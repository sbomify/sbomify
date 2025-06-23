<template>
  <StandardCard
    title="Danger Zone"
    :collapsible="true"
    :defaultExpanded="false"
    storageKey="danger-zone"
    infoIcon="fas fa-exclamation-triangle"
  >
        <!-- Transfer Component Section -->
    <div v-if="parsedIsOwner" class="mb-4">
      <h6 class="mb-3">Transfer Component to Team</h6>
      <form :action="`/components/${componentId}/transfer/`" method="post" class="row row-cols-md-auto">
        <input type="hidden" name="csrfmiddlewaretoken" :value="csrfToken">
        <div class="col">
          <label for="team_key">Team</label>
        </div>
        <div class="col">
          <select id="team_key" name="team_key" class="form-control">
            <option
              v-for="(team, teamKey) in parsedUserTeams"
              :key="teamKey"
              :value="teamKey"
            >
              {{ team.name }}
            </option>
          </select>
        </div>
        <div class="col">
          <input type="submit" class="btn btn-warning" value="Transfer Component" />
        </div>
      </form>
    </div>

    <!-- Delete Component Section -->
    <div>
      <h6 class="mb-3">Delete Component</h6>
            <a
        :id="`del_${componentId}`"
        :href="`/components/${componentId}/delete/`"
        class="btn btn-danger"
        @click.prevent="showDeleteConfirmation"
      >
        Delete Component
      </a>
    </div>

    <!-- Confirmation Modal -->
    <div
      v-if="showConfirmModal"
      class="modal fade show"
      style="display: block; background-color: rgba(0,0,0,0.5);"
      @click.self="hideDeleteConfirmation"
    >
      <div class="modal-dialog modal-dialog-centered">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title">Confirm Deletion</h5>
                        <button
              type="button"
              aria-label="Close"
              class="btn-close"
              @click="hideDeleteConfirmation"
            ></button>
          </div>
          <div class="modal-body">
            <p>Are you sure you want to delete the component <strong>{{ componentName }}</strong>?</p>
            <p class="text-warning">
              <i class="fas fa-exclamation-triangle"></i>
              This action cannot be undone.
            </p>
          </div>
          <div class="modal-footer">
            <button
              type="button"
              class="btn btn-secondary"
              @click="hideDeleteConfirmation"
            >
              Cancel
            </button>
            <a
              :href="`/components/${componentId}/delete/`"
              class="btn btn-danger"
            >
              Delete Component
            </a>
          </div>
        </div>
      </div>
    </div>
  </StandardCard>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import StandardCard from '../../../core/js/components/StandardCard.vue'

interface Team {
  name: string
}

const props = defineProps<{
  componentId: string
  componentName: string
  isOwner: string
  userTeamsElementId?: string
  csrfToken: string
}>()

const showConfirmModal = ref(false)
const parsedIsOwner = ref(false)
const parsedUserTeams = ref<Record<string, Team>>({})

const showDeleteConfirmation = (): void => {
  showConfirmModal.value = true
}

const hideDeleteConfirmation = (): void => {
  showConfirmModal.value = false
}

const parseProps = (): void => {
  try {
    // Parse isOwner boolean
    parsedIsOwner.value = props.isOwner === 'true'

    // Parse userTeams from JSON script element
    if (props.userTeamsElementId) {
      const element = document.getElementById(props.userTeamsElementId)
      if (element && element.textContent) {
        parsedUserTeams.value = JSON.parse(element.textContent)
      }
    }
  } catch (err) {
    console.error('Error parsing DangerZone props:', err)
    parsedIsOwner.value = false
    parsedUserTeams.value = {}
  }
}

onMounted(() => {
  parseProps()
})
</script>

<style scoped>
.modal {
  z-index: 1055;
}

.modal-backdrop {
  z-index: 1050;
}

.form-control {
  max-width: 200px;
}

.btn-danger {
  background-color: #dc3545;
  border-color: #dc3545;
}

.btn-danger:hover {
  background-color: #c82333;
  border-color: #bd2130;
}

.text-warning {
  color: #856404 !important;
}

h6 {
  color: #495057;
  font-weight: 600;
}
</style>