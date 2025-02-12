<template>
  <div v-if="notifications.length > 0" class="site-notifications px-4 py-2">
    <v-alert
      v-for="notification in notifications"
      :key="notification.id"
      :type="mapSeverityToType(notification.severity)"
      :text="notification.message"
      class="mb-2 custom-alert"
      variant="tonal"
      density="comfortable"
      closable
    >
      <template v-slot:append>
        <div class="d-flex align-center">
          <v-btn
            v-if="notification.action_url"
            :href="notification.action_url"
            color="primary"
            class="action-btn"
            variant="flat"
          >
            Take Action
          </v-btn>
        </div>
      </template>
    </v-alert>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import axios from 'axios'

interface Notification {
  id: string
  type: string
  message: string
  action_url?: string
  severity: 'info' | 'warning' | 'error'
  created_at: string
}

const notifications = ref<Notification[]>([])

const mapSeverityToType = (severity: string): 'info' | 'warning' | 'error' | 'success' => {
  const mapping: Record<string, 'info' | 'warning' | 'error' | 'success'> = {
    info: 'info',
    warning: 'warning',
    error: 'error'
  }
  return mapping[severity] || 'info'
}

const fetchNotifications = async () => {
  try {
    const response = await axios.get('/api/v1/notifications/')
    notifications.value = response.data
  } catch (error) {
    console.error('Failed to fetch notifications:', error)
  }
}

onMounted(() => {
  fetchNotifications()
  // Refresh notifications every 5 minutes
  setInterval(fetchNotifications, 5 * 60 * 1000)
})
</script>

<style scoped>
.site-notifications {
  background-color: transparent;
}

/* Improve action button contrast */
.action-btn {
  font-weight: 500;
  margin-left: 12px !important;
}

/* Override Vuetify's default hover opacity */
.action-btn:hover {
  opacity: 0.9;
}
</style>