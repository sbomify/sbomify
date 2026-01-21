/**
 * Notifications Modal functionality
 * Handles fetching and displaying notifications in a left-sliding modal
 */

interface Notification {
  id: string;
  type: string;
  message: string;
  action_url?: string;
  severity: 'info' | 'warning' | 'error';
  created_at: string;
}

let notifications: Notification[] = [];

function getSeverityIcon(severity: string): string {
  switch (severity) {
    case 'error':
      return 'fas fa-exclamation-circle text-danger';
    case 'warning':
      return 'fas fa-exclamation-triangle text-warning';
    case 'info':
      return 'fas fa-info-circle text-info';
    default:
      return 'fas fa-bell text-secondary';
  }
}

function getSeverityBgColor(severity: string): string {
  switch (severity) {
    case 'error':
      return 'bg-danger-subtle';
    case 'warning':
      return 'bg-warning-subtle';
    case 'info':
      return 'bg-info-subtle';
    default:
      return 'bg-secondary-subtle';
  }
}

function formatNotificationDate(dateString: string): string {
  const date = new Date(dateString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffMins < 1) {
    return 'Just now';
  } else if (diffMins < 60) {
    return `${diffMins} minute${diffMins > 1 ? 's' : ''} ago`;
  } else if (diffHours < 24) {
    return `${diffHours} hour${diffHours > 1 ? 's' : ''} ago`;
  } else if (diffDays < 7) {
    return `${diffDays} day${diffDays > 1 ? 's' : ''} ago`;
  } else {
    return date.toLocaleDateString();
  }
}

function escapeHtml(text: string): string {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

function renderNotification(notification: Notification): string {
  const icon = getSeverityIcon(notification.severity);
  const bgColor = getSeverityBgColor(notification.severity);
  const timeAgo = formatNotificationDate(notification.created_at);
  
  let actionButton = '';
  if (notification.action_url) {
    // Determine button text based on notification type
    let buttonText = 'View';
    if (notification.type === 'access_request_pending') {
      buttonText = 'Review';
    } else if (notification.type === 'community_upgrade' || notification.type.includes('billing')) {
      buttonText = 'Upgrade';
    } else if (notification.type.includes('payment') || notification.type.includes('billing')) {
      buttonText = 'Fix';
    }
    
    actionButton = `
      <a href="${escapeHtml(notification.action_url)}" class="notification-action-link">
        ${escapeHtml(buttonText)}
      </a>
    `;
  }

  return `
    <div class="notification-item ${bgColor}" data-notification-id="${escapeHtml(notification.id)}">
      <div class="notification-item-content">
        <div class="notification-icon">
          <i class="${icon}"></i>
        </div>
        <div class="notification-text">
          <p class="notification-message mb-1">${escapeHtml(notification.message)}</p>
          <small class="notification-time text-muted">${timeAgo}</small>
        </div>
      </div>
      ${actionButton}
    </div>
  `;
}

function getCsrfToken(): string {
  const cookieValue = document.cookie
    .split('; ')
    .find(row => row.startsWith('csrftoken='))
    ?.split('=')[1] || '';
  return cookieValue;
}

function renderNotifications(): void {
  const listContainer = document.getElementById('notifications-list');
  const emptyContainer = document.getElementById('notifications-empty');
  const loadingContainer = document.getElementById('notifications-loading');
  const clearAllButton = document.getElementById('clearAllNotifications');
  const badge = document.getElementById('notifications-badge');
  const badgeCount = badge?.querySelector('.notifications-count');

  if (!listContainer || !emptyContainer || !loadingContainer) return;

  loadingContainer.style.display = 'none';

  // Filter out upgrade notifications from count for "Clear All" button visibility
  const dismissibleNotifications = notifications.filter(n => n.type !== 'community_upgrade');

  if (notifications.length === 0) {
    listContainer.innerHTML = '';
    emptyContainer.style.display = 'block';
    if (clearAllButton) clearAllButton.style.display = 'none';
    if (badge) badge.style.display = 'none';
    return;
  }

  emptyContainer.style.display = 'none';
  // Only show "Clear All" if there are dismissible notifications
  if (clearAllButton) {
    clearAllButton.style.display = dismissibleNotifications.length > 0 ? 'block' : 'none';
  }
  if (badge) badge.style.display = 'block';
  if (badgeCount) badgeCount.textContent = notifications.length.toString();

  listContainer.innerHTML = notifications.map(renderNotification).join('');
}

async function fetchNotifications(): Promise<void> {
  try {
    const response = await fetch('/api/v1/notifications/', {
      method: 'GET',
      headers: {
        'X-Requested-With': 'XMLHttpRequest',
      },
    });

    if (!response.ok) {
      throw new Error(`Failed to fetch notifications: ${response.status}`);
    }

    const data = await response.json();
    notifications = Array.isArray(data) ? data : [];
    renderNotifications();
  } catch (error) {
    console.error('Error fetching notifications:', error);
    const listContainer = document.getElementById('notifications-list');
    const loadingContainer = document.getElementById('notifications-loading');
    if (loadingContainer) loadingContainer.style.display = 'none';
    if (listContainer) {
      listContainer.innerHTML = `
        <div class="text-center py-4">
          <p class="text-danger mb-0">Failed to load notifications. Please try again.</p>
        </div>
      `;
    }
  }
}

function initializeNotificationsModal(): void {
  const modal = document.getElementById('notificationsModal');
  if (!modal) return;

  const modalDialog = modal.querySelector('.modal-dialog-slide-left') as HTMLElement;
  if (!modalDialog) return;

  // Get header height
  const navbar = document.querySelector('.navbar') as HTMLElement | null;
  const headerHeight = navbar ? navbar.offsetHeight : 60;
  
  // Ensure modal starts off-screen to the right, below header
  modalDialog.style.position = 'fixed';
  modalDialog.style.top = `${headerHeight}px`;
  modalDialog.style.right = '0';
  modalDialog.style.bottom = '0';
  modalDialog.style.left = 'auto';
  modalDialog.style.width = '320px';
  modalDialog.style.maxWidth = '90vw';
  modalDialog.style.margin = '0';
  modalDialog.style.maxHeight = `calc(100vh - ${headerHeight}px)`;
  modalDialog.style.transform = 'translateX(100%)';
  modalDialog.style.transition = 'transform 0.3s ease-out';

  // Fetch notifications when modal is shown
  modal.addEventListener('show.bs.modal', () => {
    fetchNotifications();
    // Ensure it starts off-screen
    modalDialog.style.transform = 'translateX(100%)';
    // Then slide in after a tiny delay to ensure CSS is applied
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        modalDialog.style.transform = 'translateX(0)';
      });
    });
  });

  // Reset transform when modal is hidden
  modal.addEventListener('hide.bs.modal', () => {
    modalDialog.style.transform = 'translateX(100%)';
  });

  modal.addEventListener('hidden.bs.modal', () => {
    modalDialog.style.transform = 'translateX(100%)';
  });

  // Clear all notifications handler
  const clearAllButton = document.getElementById('clearAllNotifications');
  if (clearAllButton) {
    clearAllButton.addEventListener('click', async () => {
      try {
        const response = await fetch('/api/v1/notifications/clear/', {
          method: 'POST',
          headers: {
            'X-Requested-With': 'XMLHttpRequest',
            'X-CSRFToken': getCsrfToken(),
          },
        });

        if (response.ok) {
          // Refresh notifications after clearing
          await fetchNotifications();
        } else {
          console.error('Failed to clear notifications');
        }
      } catch (error) {
        console.error('Error clearing notifications:', error);
      }
    });
  }

  // Initial fetch to update badge
  fetchNotifications();
  
  // Refresh notifications periodically
  setInterval(fetchNotifications, 5 * 60 * 1000); // Every 5 minutes
}

// Initialize on DOM ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initializeNotificationsModal);
} else {
  initializeNotificationsModal();
}

// Re-initialize after HTMX swaps
document.body.addEventListener('htmx:afterSwap', () => {
  initializeNotificationsModal();
});

