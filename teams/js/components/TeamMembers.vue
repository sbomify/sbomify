<template>
  <StandardCard
    title="Team Members"
    variant="default"
    size="medium"
    shadow="sm"
  >
    <template #header-actions>
      <div class="d-flex align-items-center gap-2">
        <span class="badge bg-primary-subtle text-primary">
          {{ members.length }} member{{ members.length !== 1 ? 's' : '' }}
        </span>
      </div>
    </template>

    <div v-if="members.length === 0" class="empty-state">
      <i class="fas fa-users fa-3x text-muted mb-3"></i>
      <h5 class="text-muted mb-2">No members yet</h5>
      <p class="text-muted">Invite team members to get started</p>
    </div>

    <div v-else class="members-list">
      <div v-for="member in members" :key="member.id" class="member-card">
        <div class="member-avatar">
          <div class="avatar-circle">
            <i class="fas fa-user"></i>
          </div>
        </div>
        <div class="member-info">
          <h6 class="member-name">
            {{ member.user.first_name }} {{ member.user.last_name }}
          </h6>
          <div class="member-details">
            <span class="member-email">
              <i class="fas fa-envelope me-1"></i>
              {{ member.user.email }}
            </span>
            <span class="member-role">
              <i class="fas fa-user-tag me-1"></i>
              <span class="role-badge" :class="getRoleBadgeClass(member.role)">
                {{ member.role }}
              </span>
            </span>
          </div>
        </div>
        <div class="member-actions">
          <div class="btn-group" role="group">
            <button
              v-if="canManageMembers && member.role !== 'owner'"
              class="btn btn-sm btn-outline-danger"
              title="Remove member"
              @click="confirmRemove(member)"
            >
              <i class="fas fa-user-minus"></i>
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Remove Member Confirmation Modal -->
    <DeleteConfirmationModal
      v-model:show="showRemoveModal"
      title="Remove Member"
      message="Are you sure you want to remove"
      :item-name="memberToRemove?.user.first_name + ' ' + memberToRemove?.user.last_name"
      warning-message="This action will immediately remove the member from the team and revoke their access."
      confirm-text="Remove Member"
      @confirm="removeMember"
      @cancel="cancelRemove"
    />
  </StandardCard>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import StandardCard from '../../../core/js/components/StandardCard.vue'
import DeleteConfirmationModal from '../../../core/js/components/DeleteConfirmationModal.vue'

interface User {
  id: number
  first_name: string
  last_name: string
  email: string
}

interface Member {
  id: number
  user: User
  role: string
  is_default_team: boolean
}

const props = defineProps<{
  teamKey: string
  members: Member[]
  userRole: string
  csrfToken: string
}>()

const showRemoveModal = ref(false)
const memberToRemove = ref<Member | null>(null)

const canManageMembers = computed(() => {
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

const confirmRemove = (member: Member): void => {
  memberToRemove.value = member
  showRemoveModal.value = true
}

const cancelRemove = (): void => {
  showRemoveModal.value = false
  memberToRemove.value = null
}

const removeMember = (): void => {
  if (!memberToRemove.value) return

  // Navigate to the delete member URL
  window.location.href = `/workspace/${memberToRemove.value.id}/leave`
}
</script>

<style scoped>
.empty-state {
  padding: 3rem 0;
  text-align: center;
}

.members-list {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.member-card {
  display: flex;
  align-items: center;
  gap: 1rem;
  background: #ffffff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 1.25rem;
  transition: all 0.2s ease;
}

.member-card:hover {
  border-color: #d1d5db;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);
}

.member-avatar {
  flex-shrink: 0;
}

.avatar-circle {
  width: 48px;
  height: 48px;
  border-radius: 50%;
  background: linear-gradient(135deg, #4f46e5, #3b82f6);
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  font-size: 1.25rem;
}

.member-info {
  flex: 1;
  min-width: 0;
}

.member-name {
  font-size: 1rem;
  font-weight: 600;
  margin-bottom: 0.5rem;
  color: #1f2937;
}

.member-details {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.member-email,
.member-role {
  display: flex;
  align-items: center;
  font-size: 0.875rem;
  color: #6b7280;
}

.member-email {
  margin-bottom: 0.25rem;
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

.member-actions {
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

.bg-primary-subtle {
  background-color: #eff6ff;
}

.text-primary {
  color: #4f46e5;
}

/* Responsive design */
@media (max-width: 768px) {
  .member-card {
    flex-direction: column;
    align-items: flex-start;
    gap: 1rem;
  }

  .member-info {
    width: 100%;
  }

  .member-details {
    flex-direction: row;
    gap: 1rem;
    flex-wrap: wrap;
  }

  .member-actions {
    width: 100%;
    display: flex;
    justify-content: flex-end;
  }
}
</style>