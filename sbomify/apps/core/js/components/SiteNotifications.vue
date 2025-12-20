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
// Only show modals for new notifications that appear after initial page load
// Don't show modals on initial dashboard load - users can check notifications via the bell icon
const processNotifications = (newNotifications: Notification[], isInitialLoad: boolean = false) => {
  // Skip showing modals on initial page load
  if (isInitialLoad) {
    return
  }

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
          icon: notification.severity,
          showCancelButton: true,
          confirmButtonText: 'Take Action',
          cancelButtonText: 'Dismiss',
          customClass: {
            confirmButton: 'btn btn-primary',
            cancelButton: 'btn btn-secondary',
            actions: 'gap-2'
          },
          buttonsStyling: false
        }).then((result: import('sweetalert2').SweetAlertResult) => {
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

const fetchNotifications = async (isInitialLoad: boolean = false) => {
  try {
    const response = await axios.get('/api/v1/notifications/')
    const oldNotifications = [...notifications.value]
    notifications.value = response.data
    
    // Only process notifications if not initial load
    if (!isInitialLoad) {
      // Find new notifications that weren't in the old list
      const newItems = notifications.value.filter(
        newItem => !oldNotifications.some(oldItem => oldItem.id === newItem.id)
      )
      if (newItems.length > 0) {
        processNotifications(newItems, false)
      }
    } else {
      // On initial load, just mark all notifications as processed without showing modals
      notifications.value.forEach(notification => {
        processedNotifications.value.add(notification.id)
      })
    }
  } catch (error) {
    console.error('Failed to fetch notifications:', error)
  }
}

onMounted(() => {
  // Initial load - don't show modals
  fetchNotifications(true)
  // Refresh notifications every 5 minutes - these will show modals if new
  setInterval(() => fetchNotifications(false), 5 * 60 * 1000)
})

// Watch for changes in notifications and process new ones
// This handles notifications that appear after initial load
watch(notifications, (newNotifications, oldNotifications) => {
  if (oldNotifications.length === 0 && newNotifications.length > 0) {
    // Initial load already processed in fetchNotifications - don't show modals
    return
  }

  // Find new notifications that weren't in the old list
  const newItems = newNotifications.filter(
    newItem => !oldNotifications.some(oldItem => oldItem.id === newItem.id)
  )

  if (newItems.length > 0) {
    // Show modals for new notifications that appear after initial load
    processNotifications(newItems, false)
  }
})
</script>