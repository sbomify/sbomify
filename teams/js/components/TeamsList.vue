<template>
  <div>
    <div v-if="teams.length === 0" class="dashboard-empty">
      <p class="mb-0">No workspaces</p>
    </div>
    <table v-else class="table dashboard-table">
      <thead>
        <tr>
          <th>Name</th>
          <th>Role</th>
          <th>Members</th>
          <th>Invitations</th>
          <th class="text-end">Actions</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="team in teams" :key="team.key">
          <td>
            <a :href="`/workspace/${team.key}`" class="text-primary text-decoration-none">
              {{ team.name }}
            </a>
            <span v-if="team.is_default_team" class="badge bg-primary-subtle text-primary ms-2">Default</span>
          </td>
          <td>{{ team.role }}</td>
          <td>{{ team.member_count }}</td>
          <td>{{ team.invitation_count }}</td>
          <td class="text-end">
            <div class="actions justify-content-end">
              <button
                v-if="team.role === 'owner' && !team.is_default_team"
                class="btn btn-sm btn-danger me-2"
                title="Delete workspace"
                @click="confirmDelete(team)"
              >
                <i class="fas fa-trash"></i>
              </button>
              <a
                v-if="team.role === 'owner' || team.role === 'admin'"
                :href="`/workspace/set_default/${team.membership_id}`"
                title="Make default workspace"
                class="btn btn-sm btn-outline-primary me-2"
              >
                <i class="fas fa-star"></i>
              </a>
              <a
                v-if="team.role === 'owner'"
                :href="`/workspace/invite/${team.key}`"
                title="Invite user"
                class="btn btn-sm btn-outline-secondary"
              >
                <i class="fas fa-user-plus"></i>
              </a>
            </div>
          </td>
        </tr>
      </tbody>
    </table>

    <!-- Delete Confirmation Modal -->
    <DeleteConfirmationModal
      v-model:show="showDeleteModal"
      title="Delete Workspace"
      message="Are you sure you want to delete the workspace"
      :item-name="teamToDelete?.name"
      warning-message="This action cannot be undone and will permanently remove the workspace and all associated data from the system."
      confirm-text="Delete Workspace"
      @confirm="deleteTeam"
      @cancel="cancelDelete"
    />
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import DeleteConfirmationModal from '../../../core/js/components/DeleteConfirmationModal.vue'

interface Team {
  key: string
  name: string
  role: string
  member_count: number
  invitation_count: number
  is_default_team: boolean
  membership_id: string
}

const props = defineProps<{
  teamsDataElementId: string
  csrfToken: string
}>()

const teams = ref<Team[]>([])
const showDeleteModal = ref(false)
const teamToDelete = ref<Team | null>(null)

const confirmDelete = (team: Team): void => {
  teamToDelete.value = team
  showDeleteModal.value = true
}

const cancelDelete = (): void => {
  showDeleteModal.value = false
  teamToDelete.value = null
}

const deleteTeam = (): void => {
  if (!teamToDelete.value) return

  // Navigate to the delete URL
  window.location.href = `/workspace/delete/${teamToDelete.value.key}`
}

const loadTeams = (): void => {
  try {
    const element = document.getElementById(props.teamsDataElementId)
    if (element && element.textContent) {
      teams.value = JSON.parse(element.textContent)
    }
  } catch (error) {
    console.error('Error loading teams data:', error)
    teams.value = []
  }
}

// Load teams when component mounts
loadTeams()
</script>

<style scoped>
.dashboard-empty {
  padding: 2rem 0;
  text-align: center;
  color: #6c757d;
}

.actions {
  display: flex;
  gap: 0.25rem;
}

.btn-sm {
  padding: 0.25rem 0.5rem;
  font-size: 0.875rem;
}

.badge {
  font-size: 0.75rem;
}
</style>