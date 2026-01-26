import Alpine from 'alpinejs';
import { showSuccess, showError, showWarning, showInfo } from './alerts';

/**
 * Django Messages Component
 * Processes Django messages stored in x-ref script template and displays them as toasts
 */
export function registerDjangoMessages() {
  Alpine.data('djangoMessages', () => {
    return {
      processed: false,
      
      init() {
        if (this.processed) return;
        this.processMessages();
      },
      
      processMessages() {
        // Read data from x-ref script template
        let messagesData = '';
        try {
          const dataElement = this.$refs.djangoMessagesData as HTMLElement;
          if (dataElement && dataElement.textContent) {
            messagesData = dataElement.textContent.trim();
          }
        } catch (error) {
          console.error('Failed to read Django messages data:', error);
          return;
        }
        
        if (!messagesData) {
          return;
        }

        const messages = messagesData.split('|').filter(Boolean);
        messages.forEach((messageData: string) => {
          const [tags, message] = messageData.split(':');

          // Map Django message levels to alert types
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
        
        this.processed = true;
      }
    };
  });
}

// Legacy function for backwards compatibility
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