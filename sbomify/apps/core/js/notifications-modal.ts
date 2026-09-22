/** Notification data and lifecycle. Cotton templates own all rendered markup. */
import { getCsrfToken } from './csrf';
import { formatCompactRelativeDate } from './utils';

interface Notification {
  id: string;
  type: string;
  message: string;
  action_url?: string;
  severity: 'info' | 'warning' | 'error';
  created_at: string;
}

let notifications: Notification[] = [];
let initializedPanel: HTMLElement | null = null;

function actionLabel(type: string): string {
  if (type === 'pending_invitation') return 'Respond';
  if (type === 'access_request_pending') return 'Review';
  if (type === 'community_upgrade' || type.includes('billing')) return 'Upgrade';
  if (type.includes('payment')) return 'Fix payment';
  return 'View';
}

function renderNotification(notification: Notification, template: HTMLTemplateElement): DocumentFragment {
  const row = template.content.cloneNode(true) as DocumentFragment;
  const item = row.querySelector<HTMLElement>('li');
  const message = row.querySelector<HTMLElement>('[data-notification-message]');
  const time = row.querySelector<HTMLTimeElement>('[data-notification-time]');
  const action = row.querySelector<HTMLAnchorElement>('[data-notification-action]');
  if (item) {
    item.dataset.notificationId = notification.id;
    item.dataset.severity = notification.severity;
  }
  if (message) message.textContent = notification.message;
  if (time) {
    time.textContent = formatCompactRelativeDate(notification.created_at);
    time.dateTime = notification.created_at;
  }
  // Only web links can become actions, even if an API response is malformed.
  const url = notification.action_url ? new URL(notification.action_url, window.location.origin) : null;
  if (action && url && ['http:', 'https:'].includes(url.protocol)) {
    action.href = url.href;
    action.textContent = actionLabel(notification.type);
  } else {
    row.querySelector('[data-notification-action-wrapper]')?.remove();
  }
  return row;
}

function setHidden(id: string, hidden: boolean): void {
  document.getElementById(id)?.classList.toggle('hidden', hidden);
}

function renderNotifications(): void {
  const list = document.getElementById('notifications-list');
  const template = document.getElementById('notification-item-template');
  if (!list || !(template instanceof HTMLTemplateElement)) return;

  list.replaceChildren(...notifications.map(notification => renderNotification(notification, template)));
  setHidden('notifications-loading', true);
  setHidden('notifications-error', true);
  setHidden('notifications-empty', notifications.length > 0);
  setHidden('notifications-clear', notifications.length === 0);
  setHidden('notifications-badge', notifications.length === 0);
  const count = document.querySelector('[data-notification-count]');
  if (count) count.textContent = `${notifications.length} new notifications`;
}

async function fetchNotifications(): Promise<void> {
  try {
    const response = await fetch('/api/v1/notifications/', {
      method: 'GET',
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
    });
    if (!response.ok) throw new Error(`Failed to fetch notifications: ${response.status}`);
    const data = await response.json();
    notifications = Array.isArray(data) ? data : [];
    renderNotifications();
  } catch {
    setHidden('notifications-loading', true);
    setHidden('notifications-empty', true);
    setHidden('notifications-clear', true);
    setHidden('notifications-error', false);
    document.getElementById('notifications-list')?.replaceChildren();
  }
}

function refreshNotifications(): void {
  document.getElementById('notifications-dropdown')?.focus();
  setHidden('notifications-loading', false);
  setHidden('notifications-empty', true);
  setHidden('notifications-error', true);
  setHidden('notifications-clear', true);
  document.getElementById('notifications-list')?.replaceChildren();
  void fetchNotifications();
}

const POLLING_INTERVAL = 5 * 60 * 1000;
let pollingIntervalId: ReturnType<typeof setInterval> | null = null;

function startPolling(): void {
  if (!pollingIntervalId) pollingIntervalId = setInterval(fetchNotifications, POLLING_INTERVAL);
}

function stopPolling(): void {
  if (pollingIntervalId) clearInterval(pollingIntervalId);
  pollingIntervalId = null;
}

function initializeNotificationsDropdown(): void {
  const panel = document.getElementById('notifications-dropdown');
  if (!panel || panel === initializedPanel) return;
  initializedPanel = panel;
  void fetchNotifications();
  if (!document.hidden) startPolling();
}

// Register document listeners once; HTMX can replace the panel many times.
document.addEventListener('notifications-open', refreshNotifications);
document.addEventListener('visibilitychange', () => {
  if (document.hidden) {
    stopPolling();
  } else if (document.getElementById('notifications-dropdown')) {
    void fetchNotifications();
    startPolling();
  }
});
document.addEventListener('click', async event => {
  const target = event.target instanceof Element ? event.target.closest('button') : null;
  if (target?.id === 'notifications-retry') {
    refreshNotifications();
  } else if (target?.id === 'clearAllNotifications') {
    document.getElementById('notifications-dropdown')?.focus();
    target.disabled = true;
    try {
      const response = await fetch('/api/v1/notifications/clear/', {
        method: 'POST',
        headers: {
          'X-Requested-With': 'XMLHttpRequest',
          'X-CSRFToken': getCsrfToken(),
        },
      });
      if (response.ok) await fetchNotifications();
    } catch {
      // Keep the current notifications available until the next refresh.
    } finally {
      target.disabled = false;
      document.getElementById('notifications-dropdown')?.focus();
    }
  }
});
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initializeNotificationsDropdown);
} else {
  initializeNotificationsDropdown();
}
document.body.addEventListener('htmx:afterSwap', initializeNotificationsDropdown);
