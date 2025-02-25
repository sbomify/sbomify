<template>
  <!-- Empty template as we'll handle notifications via SweetAlert2 -->
</template>

<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import axios from 'axios'
import { showError, showWarning, showInfo } from '../alerts'

interface Notification {
  id: string
  type: string
  message: string
  action_url?: string
  severity: 'info' | 'warning' | 'error'
  created_at: string
}

// Store notifications in memory to avoid showing duplicates
const notifications = ref<Notification[]>([])
const processedNotifications = ref<Set<string>>(new Set())

// Process notifications and show them using SweetAlert2
const processNotifications = (newNotifications: Notification[]) => {
  newNotifications.forEach(notification => {
    // Skip if we've already processed this notification
    if (processedNotifications.value.has(notification.id)) {
      return
    }

    // Mark as processed
    processedNotifications.value.add(notification.id)

    // Show the appropriate alert based on severity
    const showAlert = (message: string) => {
      switch (notification.severity) {
        case 'error':
          return showError(message)
        case 'warning':
          return showWarning(message)
        case 'info':
          return showInfo(message)
        default:
          return showInfo(message)
      }
    }

    // If there's an action URL, include it in the message
    let message = notification.message
    if (notification.action_url) {
      // Show a more persistent alert with action button for actionable notifications
      import('sweetalert2').then(({ default: Swal }) => {
        Swal.fire({
          title: notification.severity.charAt(0).toUpperCase() + notification.severity.slice(1),
          text: notification.message,
          icon: notification.severity as any,
          showCancelButton: true,
          confirmButtonText: 'Take Action',
          cancelButtonText: 'Dismiss',
          customClass: {
            confirmButton: 'btn btn-primary',
            cancelButton: 'btn btn-secondary',
            actions: 'gap-2'
          },
          buttonsStyling: false
        }).then((result) => {
          if (result.isConfirmed && notification.action_url) {
            window.location.href = notification.action_url
          }
        })
      })
    } else {
      // For non-actionable notifications, show a simple toast
      showAlert(message)
    }
  })
}

const fetchNotifications = async () => {
  try {
    const response = await axios.get('/api/v1/notifications/')
    notifications.value = response.data
    processNotifications(notifications.value)
  } catch (error) {
    console.error('Failed to fetch notifications:', error)
  }
}

onMounted(() => {
  fetchNotifications()
  // Refresh notifications every 5 minutes
  setInterval(fetchNotifications, 5 * 60 * 1000)
})

// Watch for changes in notifications and process new ones
watch(notifications, (newNotifications, oldNotifications) => {
  if (oldNotifications.length === 0 && newNotifications.length > 0) {
    // Initial load already processed in fetchNotifications
    return
  }

  // Find new notifications that weren't in the old list
  const newItems = newNotifications.filter(
    newItem => !oldNotifications.some(oldItem => oldItem.id === newItem.id)
  )

  if (newItems.length > 0) {
    processNotifications(newItems)
  }
})
</script>