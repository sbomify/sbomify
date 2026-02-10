/**
 * Notifications Dropdown functionality
 * Handles fetching and displaying notifications in a header dropdown
 */
import { getCsrfToken } from './csrf';

interface Notification {
  id: string;
  type: string;
  message: string;
  action_url?: string;
  severity: 'info' | 'warning' | 'error';
  created_at: string;
}

let notifications: Notification[] = [];
let clearAllButtonInitialized = false;
let globalListenersInitialized = false;

function getSeverityIcon(severity: string): string {
  switch (severity) {
    case 'error':
      return 'fas fa-exclamation-circle';
    case 'warning':
      return 'fas fa-exclamation-triangle';
    case 'info':
      return 'fas fa-info-circle';
    default:
      return 'fas fa-bell';
  }
}

function getSeverityColors(severity: string): {
  bg: string;
  icon: string;
  iconBg: string;
  accent: string;
  btnBg: string;
  btnHover: string;
} {
  switch (severity) {
    case 'error':
      return {
        bg: 'bg-gradient-to-r from-danger/10 to-danger/5 hover:from-danger/15 hover:to-danger/10',
        icon: 'text-danger',
        iconBg: 'bg-danger/20',
        accent: 'border-l-danger',
        btnBg: 'bg-danger/10 text-danger',
        btnHover: 'hover:bg-danger hover:text-white'
      };
    case 'warning':
      return {
        bg: 'bg-gradient-to-r from-warning/10 to-warning/5 hover:from-warning/15 hover:to-warning/10',
        icon: 'text-warning',
        iconBg: 'bg-warning/20',
        accent: 'border-l-warning',
        btnBg: 'bg-warning/10 text-warning',
        btnHover: 'hover:bg-warning hover:text-white'
      };
    case 'info':
      return {
        bg: 'bg-gradient-to-r from-info/10 to-info/5 hover:from-info/15 hover:to-info/10',
        icon: 'text-info',
        iconBg: 'bg-info/20',
        accent: 'border-l-info',
        btnBg: 'bg-info/10 text-info',
        btnHover: 'hover:bg-info hover:text-white'
      };
    default:
      return {
        bg: 'bg-surface hover:bg-border/20',
        icon: 'text-text-muted',
        iconBg: 'bg-border/30',
        accent: 'border-l-border',
        btnBg: 'bg-primary/10 text-primary',
        btnHover: 'hover:bg-primary hover:text-white'
      };
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
    return `${diffMins}m ago`;
  } else if (diffHours < 24) {
    return `${diffHours}h ago`;
  } else if (diffDays < 7) {
    return `${diffDays}d ago`;
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
  const colors = getSeverityColors(notification.severity);
  const timeAgo = formatNotificationDate(notification.created_at);

  let actionButton = '';
  if (notification.action_url) {
    let buttonText = 'View';
    let buttonIcon = 'fa-arrow-right';
    if (notification.type === 'access_request_pending') {
      buttonText = 'Review';
      buttonIcon = 'fa-eye';
    } else if (notification.type === 'community_upgrade' || notification.type.includes('billing')) {
      buttonText = 'Upgrade';
      buttonIcon = 'fa-rocket';
    } else if (notification.type.includes('payment')) {
      buttonText = 'Fix Payment';
      buttonIcon = 'fa-credit-card';
    }

    actionButton = `
      <a href="${escapeHtml(notification.action_url)}"
         class="inline-flex items-center gap-1.5 text-xs font-semibold px-3 py-1.5 rounded-lg ${colors.btnBg} ${colors.btnHover} transition-all duration-200 no-underline shadow-sm">
        ${escapeHtml(buttonText)}
        <i class="fas ${buttonIcon} text-[10px]"></i>
      </a>
    `;
  }

  return `
    <div class="px-4 py-4 ${colors.bg} border-l-4 ${colors.accent} transition-all duration-200" data-notification-id="${escapeHtml(notification.id)}">
      <div class="flex items-start gap-3">
        <div class="w-10 h-10 rounded-xl ${colors.iconBg} flex items-center justify-center flex-shrink-0 shadow-sm">
          <i class="${icon} ${colors.icon} text-base"></i>
        </div>
        <div class="flex-1 min-w-0">
          <p class="text-sm text-text leading-relaxed mb-3">${escapeHtml(notification.message)}</p>
          <div class="flex items-center justify-between gap-3">
            <span class="text-[11px] text-text-muted flex items-center gap-1.5 bg-background/50 px-2 py-1 rounded-md">
              <i class="far fa-clock text-[10px]"></i>
              ${timeAgo}
            </span>
            ${actionButton}
          </div>
        </div>
      </div>
    </div>
  `;
}

function renderNotifications(): void {
  const listContainer = document.getElementById('notifications-list');
  const emptyContainer = document.getElementById('notifications-empty');
  const loadingContainer = document.getElementById('notifications-loading');
  const clearAllButton = document.getElementById('clearAllNotifications');
  const badge = document.getElementById('notifications-badge');

  if (!listContainer || !emptyContainer || !loadingContainer) return;

  // Hide loading state
  loadingContainer.classList.add('hidden');

  // Filter out upgrade notifications from count for "Clear All" button visibility
  const dismissibleNotifications = notifications.filter(n => n.type !== 'community_upgrade');

  if (notifications.length === 0) {
    listContainer.innerHTML = '';
    // Show empty state
    emptyContainer.classList.remove('hidden');
    if (clearAllButton) clearAllButton.classList.add('hidden');
    if (badge) {
      badge.classList.add('hidden');
      badge.textContent = '';
    }
    return;
  }

  // Hide empty state
  emptyContainer.classList.add('hidden');
  // Only show "Clear All" if there are dismissible notifications
  if (clearAllButton) {
    if (dismissibleNotifications.length > 0) {
      clearAllButton.classList.remove('hidden');
    } else {
      clearAllButton.classList.add('hidden');
    }
  }
  // Update badge with count
  if (badge) {
    badge.classList.remove('hidden');
    badge.textContent = notifications.length > 99 ? '99+' : String(notifications.length);
  }

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
  } catch {
    const listContainer = document.getElementById('notifications-list');
    const loadingContainer = document.getElementById('notifications-loading');
    if (loadingContainer) loadingContainer.classList.add('hidden');
    if (listContainer) {
      // Static error message - no user input involved
      listContainer.innerHTML = `
        <div class="flex flex-col items-center justify-center py-12 px-6">
          <div class="w-14 h-14 rounded-full bg-danger/10 flex items-center justify-center mb-4">
            <i class="fas fa-exclamation-triangle text-xl text-danger"></i>
          </div>
          <p class="text-sm text-text font-semibold mb-1">Failed to load notifications</p>
          <p class="text-xs text-text-muted text-center">Please try again later.</p>
        </div>
      `;
    }
  }
}

function resetLoadingState(): void {
  const loadingContainer = document.getElementById('notifications-loading');
  const emptyContainer = document.getElementById('notifications-empty');
  const listContainer = document.getElementById('notifications-list');

  if (loadingContainer) loadingContainer.classList.remove('hidden');
  if (emptyContainer) emptyContainer.classList.add('hidden');
  if (listContainer) listContainer.innerHTML = '';
}

function initializeClearAllButton(): void {
  if (clearAllButtonInitialized) return;

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
          await fetchNotifications();
        }
      } catch {
        // Silently fail - notifications will refresh on next poll
      }
    });
    clearAllButtonInitialized = true;
  }
}

const POLLING_INTERVAL = 5 * 60 * 1000; // 5 minutes
let pollingIntervalId: ReturnType<typeof setInterval> | null = null;

function startPolling(): void {
  if (pollingIntervalId) return; // Already polling
  pollingIntervalId = setInterval(fetchNotifications, POLLING_INTERVAL);
}

function stopPolling(): void {
  if (pollingIntervalId) {
    clearInterval(pollingIntervalId);
    pollingIntervalId = null;
  }
}

function initializeNotificationsDropdown(): void {
  const dropdown = document.getElementById('notifications-dropdown');
  if (!dropdown) return;

  // Initialize clear all button (re-bind after DOM swap)
  initializeClearAllButton();

  // Only register global listeners once — they survive hx-boost swaps
  // because they are on `document`, not on swapped DOM elements.
  if (!globalListenersInitialized) {
    globalListenersInitialized = true;

    // Listen for dropdown open event from Alpine.js
    document.addEventListener('notifications-open', () => {
      resetLoadingState();
      fetchNotifications();
    });

    // Start polling only when page is visible
    if (!document.hidden) {
      startPolling();
    }

    // Use Page Visibility API to pause polling when tab is not visible
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) {
        stopPolling();
      } else {
        // Fetch immediately when tab becomes visible, then resume polling
        fetchNotifications();
        startPolling();
      }
    });
  }

  // Update badge with cached data (no extra API call on navigation)
  renderNotifications();
}

// Initialize on DOM ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initializeNotificationsDropdown);
} else {
  initializeNotificationsDropdown();
}

// Re-initialize after HTMX swaps (including boosted navigations).
// DOM elements are replaced on every swap, so button handlers and badge
// state need re-binding. Global listeners (polling, visibility) survive
// because they are on `document`, not on swapped DOM elements.
document.body.addEventListener('htmx:afterSwap', (() => {
  clearAllButtonInitialized = false;
  initializeNotificationsDropdown();
}) as EventListener);
