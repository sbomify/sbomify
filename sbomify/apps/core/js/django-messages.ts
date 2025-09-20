import { showSuccess, showError, showWarning, showInfo } from './alerts';

/**
 * Process Django messages stored in the DOM and display them using SweetAlert2
 */
export function processDjangoMessages() {
  const messagesContainer = document.getElementById('django-messages');
  if (!messagesContainer || !messagesContainer.dataset.messages) {
    return;
  }

  const messages = messagesContainer.dataset.messages.split('|').filter(Boolean);
  messages.forEach(messageData => {
    const [tags, message] = messageData.split(':');

    // Map Django message levels to SweetAlert2 types
    if (tags.includes('success')) {
      showSuccess(message);
    } else if (tags.includes('error')) {
      showError(message);
    } else if (tags.includes('warning')) {
      showWarning(message);
    } else if (tags.includes('info') || tags.includes('debug')) {
      showInfo(message);
    }
  });
}

// Initialize message processing when the DOM is ready
document.addEventListener('DOMContentLoaded', processDjangoMessages);