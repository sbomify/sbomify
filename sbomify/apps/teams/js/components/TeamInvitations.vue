<template>
  <StandardCard
    title="Pending Invitations"
    variant="default"
    size="medium"
    shadow="sm"
  >
    <template #header-actions>
      <div class="d-flex align-items-center gap-2">
        <span class="badge bg-warning-subtle text-warning">
          {{ invitations.length }} pending
        </span>
        <a
          v-if="canInviteUsers"
          :href="`/workspace/invite/${teamKey}`"
          class="btn btn-sm btn-primary"
        >
          <i class="fas fa-user-plus me-2"></i>
          Invite Member
        </a>
      </div>
    </template>

    <div v-if="invitations.length === 0" class="empty-state">
      <i class="fas fa-envelope fa-3x text-muted mb-3"></i>
      <h5 class="text-muted mb-2">No pending invitations</h5>
      <p class="text-muted">Invite team members to get started</p>
    </div>

    <div v-else class="invitations-list">
      <div v-for="invitation in invitations" :key="invitation.id" class="invitation-card">
        <div class="invitation-avatar">
          <div class="avatar-circle">
            <i class="fas fa-envelope"></i>
          </div>
        </div>
        <div class="invitation-info">
          <h6 class="invitation-email">
            {{ invitation.email }}
          </h6>
          <div class="invitation-details">
            <span class="invitation-role">
              <i class="fas fa-user-tag me-1"></i>
              <span class="role-badge" :class="getRoleBadgeClass(invitation.role)">
                {{ invitation.role }}
              </span>
            </span>
            <span class="invitation-date">
              <i class="fas fa-clock me-1"></i>
              Invited {{ formatDate(invitation.created_at) }}
            </span>
            <span class="invitation-expires">
              <i class="fas fa-hourglass-half me-1"></i>
              Expires {{ formatDate(invitation.expires_at) }}
            </span>
          </div>
        </div>
        <div class="invitation-actions">
          <div class="btn-group" role="group">
            <button
              v-if="canManageInvitations"
              class="btn btn-sm btn-outline-danger"
              title="Cancel invitation"
              @click="confirmCancel(invitation)"
            >
              <i class="fas fa-times"></i>
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Cancel Invitation Confirmation Modal -->
    <DeleteConfirmationModal
      v-model:show="showCancelModal"
      title="Cancel Invitation"
      message="Are you sure you want to cancel the invitation for"
      :item-name="invitationToCancel?.email"
      warning-message="This action will immediately cancel the invitation and the user will no longer be able to join the team using this invite."
      confirm-text="Cancel Invitation"
      @confirm="cancelInvitation"
      @cancel="cancelCancelInvitation"
    />
  </StandardCard>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import StandardCard from '../../../core/js/components/StandardCard.vue'
import DeleteConfirmationModal from '../../../core/js/components/DeleteConfirmationModal.vue'

interface Invitation {
  id: number
  email: string
  role: string
  created_at: string
  expires_at: string
}

const props = defineProps<{
  teamKey: string
  invitations: Invitation[]
  userRole: string
  csrfToken: string
}>()

const showCancelModal = ref(false)
const invitationToCancel = ref<Invitation | null>(null)

const canInviteUsers = computed(() => {
  return props.userRole === 'owner' || props.userRole === 'admin'
})

const canManageInvitations = computed(() => {
  return props.userRole === 'owner' || props.userRole === 'admin'
})

const getRoleBadgeClass = (role: string): string => {
  switch (role) {
    case 'owner':
      return 'role-owner'
    case 'admin':
      return 'role-admin'
    case 'guest':
      return 'role-guest'
    default:
      return 'role-member'
  }
}

const formatDate = (dateString: string): string => {
  const date = new Date(dateString)
  return date.toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric'
  })
}

const confirmCancel = (invitation: Invitation): void => {
  invitationToCancel.value = invitation
  showCancelModal.value = true
}

const cancelCancelInvitation = (): void => {
  showCancelModal.value = false
  invitationToCancel.value = null
}

const cancelInvitation = (): void => {
  if (!invitationToCancel.value) return

  // Navigate to the cancel invitation URL
  window.location.href = `/workspace/${invitationToCancel.value.id}/uninvite`
}
</script>

<style scoped>
.empty-state {
  padding: 3rem 0;
  text-align: center;
}

.invitations-list {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.invitation-card {
  display: flex;
  align-items: center;
  gap: 1rem;
  background: #ffffff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 1.25rem;
  transition: all 0.2s ease;
}

.invitation-card:hover {
  border-color: #d1d5db;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);
}

.invitation-avatar {
  flex-shrink: 0;
}

.avatar-circle {
  width: 48px;
  height: 48px;
  border-radius: 50%;
  background: linear-gradient(135deg, #f59e0b, #f97316);
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  font-size: 1.25rem;
}

.invitation-info {
  flex: 1;
  min-width: 0;
}

.invitation-email {
  font-size: 1rem;
  font-weight: 600;
  margin-bottom: 0.5rem;
  color: #1f2937;
}

.invitation-details {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.invitation-role,
.invitation-date,
.invitation-expires {
  display: flex;
  align-items: center;
  font-size: 0.875rem;
  color: #6b7280;
}

.role-badge {
  display: inline-block;
  padding: 0.125rem 0.5rem;
  border-radius: 9999px;
  font-size: 0.75rem;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.025em;
}

.role-owner {
  background-color: #fef3c7;
  color: #92400e;
}

.role-admin {
  background-color: #dbeafe;
  color: #1e40af;
}

.role-guest {
  background-color: #f3f4f6;
  color: #374151;
}

.role-member {
  background-color: #e5e7eb;
  color: #4b5563;
}

.invitation-actions {
  flex-shrink: 0;
}

.btn-group .btn {
  border-radius: 6px;
}

.btn-sm {
  padding: 0.375rem 0.75rem;
  font-size: 0.875rem;
  line-height: 1.25;
}

.btn-primary {
  background: linear-gradient(135deg, #4f46e5, #3b82f6);
  border: none;
  color: white;
}

.btn-primary:hover {
  background: linear-gradient(135deg, #3730a3, #2563eb);
}

.btn-outline-danger {
  color: #ef4444;
  border-color: #ef4444;
}

.btn-outline-danger:hover {
  background-color: #ef4444;
  border-color: #ef4444;
  color: white;
}

.badge {
  font-size: 0.75rem;
  font-weight: 500;
  padding: 0.25rem 0.5rem;
}

.bg-warning-subtle {
  background-color: #fef3c7;
}

.text-warning {
  color: #f59e0b;
}

/* Responsive design */
@media (max-width: 768px) {
  .invitation-card {
    flex-direction: column;
    align-items: flex-start;
    gap: 1rem;
  }

  .invitation-info {
    width: 100%;
  }

  .invitation-details {
    flex-direction: row;
    gap: 1rem;
    flex-wrap: wrap;
  }

  .invitation-actions {
    width: 100%;
    display: flex;
    justify-content: flex-end;
  }
}
</style>