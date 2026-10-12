import { showToast } from './alerts';

let initialized = false;

function showMessage(level: string, message: string): void {
  const value = level.replace(/^alert-/, '');
  const type = value === 'error' || value === 'danger' ? 'error'
    : value === 'success' || value === 'warning' ? value : 'info';
  showToast({ title: type.charAt(0).toUpperCase() + type.slice(1), message, type });
}

function showSessionNotice(key: string, title: string, message: string): void {
  try {
    if (sessionStorage.getItem(key)) return;
    sessionStorage.setItem(key, 'shown');
  } catch {
    // Blocked storage must not prevent the notice or the remaining messages.
  }
  showToast({ title, message, type: 'info' });
}

/** Consume escaped text once, before HTMX can save it in its history cache. */
export function processDjangoMessages(): void {
  document.querySelectorAll<HTMLElement>('[data-django-messages]').forEach(container => {
    container.remove();
    container.querySelectorAll<HTMLElement>('[data-level]').forEach(message => {
      showMessage(message.dataset.level || 'info', message.textContent || '');
    });
    const invitations = Number(container.dataset.pendingInvitations);
    if (invitations > 0) {
      showSessionNotice('session_invitation_toast_shown', 'Workspace Invitation',
        invitations === 1
          ? 'You have a workspace invitation! Check your settings to accept it.'
          : `You have ${invitations} workspace invitations! Check your settings to accept them.`);
    }
    const requests = Number(container.dataset.pendingAccessRequests);
    if (requests > 0) {
      showSessionNotice('session_access_request_toast_shown', 'Access Request',
        requests === 1 ? 'You have a pending access request to review!'
          : `You have ${requests} pending access requests to review!`);
    }
  });
}

/** Called after Alpine starts, so its toast listener is ready on every page. */
export function initDjangoMessages(): void {
  if (initialized) return;
  initialized = true;
  processDjangoMessages();
  document.body.addEventListener('htmx:load', processDjangoMessages);
  document.body.addEventListener('messages', (event: Event) => {
    const messages = (event as CustomEvent).detail?.value;
    if (!Array.isArray(messages)) return;
    messages.forEach(message => {
      if (typeof message?.message === 'string') {
        showMessage(typeof message.type === 'string' ? message.type : 'info', message.message);
      }
    });
  });
}
