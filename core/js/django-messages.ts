import { NotificationManager } from './utils/django-components';

/**
 * Process Django messages stored in the DOM and display them using Bootstrap 5 toasts
 */
export function processDjangoMessages() {
  const messagesContainer = document.getElementById('django-messages');
  if (!messagesContainer || !messagesContainer.dataset.messages) {
    return;
  }

  const messages = messagesContainer.dataset.messages.split('|').filter(Boolean);
  messages.forEach(messageData => {
    const [tags, message] = messageData.split(':');

    // Map Django message levels to Bootstrap toast types
    if (tags.includes('success')) {
      NotificationManager.showSuccess(message);
    } else if (tags.includes('error')) {
      NotificationManager.showError(message);
    } else if (tags.includes('warning')) {
      NotificationManager.showWarning(message);
    } else if (tags.includes('info') || tags.includes('debug')) {
      NotificationManager.showSuccess(message); // Use success for info messages
    }
  });
}

// Initialize message processing when the DOM is ready
document.addEventListener('DOMContentLoaded', processDjangoMessages);