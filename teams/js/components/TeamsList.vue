<template>
  <StandardCard
    title="Your Workspaces"
    variant="default"
    size="medium"
    shadow="sm"
  >
    <template #header-actions>
      <div class="d-flex align-items-center gap-2">
        <span class="badge bg-primary-subtle text-primary">
          {{ teams.length }} workspace{{ teams.length !== 1 ? 's' : '' }}
        </span>
      </div>
    </template>

    <div v-if="teams.length === 0" class="dashboard-empty">
      <div class="empty-state">
        <i class="fas fa-users fa-3x text-muted mb-3"></i>
        <h5 class="text-muted mb-2">No workspaces yet</h5>
        <p class="text-muted">Create your first workspace to get started with sbomify</p>
      </div>
    </div>

    <div v-else class="teams-grid">
      <div v-for="team in teams" :key="team.key" class="team-card">
        <div class="team-card-header">
          <div class="team-info">
            <h6 class="team-name">
              <a :href="`/workspace/${team.key}`" class="text-decoration-none">
                {{ team.name }}
              </a>
              <span v-if="team.is_default_team" class="badge bg-primary ms-2">Default</span>
            </h6>
            <div class="team-meta">
              <span class="meta-item">
                <i class="fas fa-user-tag me-1"></i>
                {{ team.role }}
              </span>
              <span class="meta-divider">•</span>
              <span class="meta-item">
                <i class="fas fa-users me-1"></i>
                {{ team.member_count }} member{{ team.member_count !== 1 ? 's' : '' }}
              </span>
              <span v-if="team.invitation_count > 0" class="meta-divider">•</span>
              <span v-if="team.invitation_count > 0" class="meta-item">
                <i class="fas fa-envelope me-1"></i>
                {{ team.invitation_count }} pending
              </span>
            </div>
          </div>
          <div class="team-actions">
            <div class="btn-group" role="group">
              <a
                v-if="team.role === 'owner' || team.role === 'admin'"
                :href="`/workspace/set_default/${team.membership_id}`"
                :title="team.is_default_team ? 'Already default workspace' : 'Make default workspace'"
                class="btn btn-sm btn-outline-primary"
                :class="{ 'disabled': team.is_default_team }"
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
              <button
                v-if="team.role === 'owner' && !team.is_default_team"
                class="btn btn-sm btn-outline-danger"
                title="Delete workspace"
                @click="confirmDelete(team)"
              >
                <i class="fas fa-trash"></i>
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>

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
  </StandardCard>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import StandardCard from '../../../core/js/components/StandardCard.vue'
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
  padding: 3rem 0;
  text-align: center;
}

.empty-state {
  max-width: 400px;
  margin: 0 auto;
}

.teams-grid {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.team-card {
  background: #ffffff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 1.5rem;
  transition: all 0.2s ease;
}

.team-card:hover {
  border-color: #d1d5db;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);
  transform: translateY(-1px);
}

.team-card-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 1rem;
}

.team-info {
  flex: 1;
}

.team-name {
  font-size: 1.1rem;
  font-weight: 600;
  margin-bottom: 0.5rem;
  color: #1f2937;
}

.team-name a {
  color: #4f46e5;
  transition: color 0.2s ease;
}

.team-name a:hover {
  color: #3730a3;
}

.team-meta {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
  font-size: 0.875rem;
  color: #6b7280;
}

.meta-item {
  display: flex;
  align-items: center;
  white-space: nowrap;
}

.meta-divider {
  color: #d1d5db;
  font-weight: bold;
}

.team-actions {
  display: flex;
  align-items: center;
}

.btn-group .btn {
  border-radius: 6px;
  margin-left: 0.25rem;
}

.btn-group .btn:first-child {
  margin-left: 0;
}

.btn-sm {
  padding: 0.375rem 0.75rem;
  font-size: 0.875rem;
  line-height: 1.25;
}

.btn-outline-primary {
  color: #4f46e5;
  border-color: #4f46e5;
}

.btn-outline-primary:hover {
  background-color: #4f46e5;
  border-color: #4f46e5;
}

.btn-outline-secondary {
  color: #6b7280;
  border-color: #6b7280;
}

.btn-outline-secondary:hover {
  background-color: #6b7280;
  border-color: #6b7280;
}

.btn-outline-danger {
  color: #ef4444;
  border-color: #ef4444;
}

.btn-outline-danger:hover {
  background-color: #ef4444;
  border-color: #ef4444;
}

.btn.disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.badge {
  font-size: 0.75rem;
  font-weight: 500;
  padding: 0.25rem 0.5rem;
}

.bg-primary-subtle {
  background-color: #eff6ff;
}

.text-primary {
  color: #4f46e5;
}

.bg-primary {
  background-color: #4f46e5;
}

/* Responsive design */
@media (max-width: 768px) {
  .team-card-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 1rem;
  }

  .team-actions {
    width: 100%;
    justify-content: flex-end;
  }

  .team-meta {
    flex-direction: column;
    align-items: flex-start;
    gap: 0.25rem;
  }

  .meta-divider {
    display: none;
  }
}
</style>