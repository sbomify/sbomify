document.addEventListener('DOMContentLoaded', function() {
  const NOTIFICATION_TIMEOUT = 4000; // 4 seconds

  function setupNotification(notification) {
    // Start the auto-dismiss timer
    const timer = setTimeout(() => {
      const alert = bootstrap.Alert.getOrCreateInstance(notification);
      alert.close();
    }, NOTIFICATION_TIMEOUT);

    // Stop the timer if user hovers over notification
    notification.addEventListener('mouseenter', () => clearTimeout(timer));

    // Restart the timer when user leaves the notification
    notification.addEventListener('mouseleave', () => {
      const newTimer = setTimeout(() => {
        const alert = bootstrap.Alert.getOrCreateInstance(notification);
        alert.close();
      }, NOTIFICATION_TIMEOUT);
      notification.dataset.timerId = newTimer;
    });
  }

  // Set up existing notifications
  document.querySelectorAll('.alert').forEach(setupNotification);

  // Set up a mutation observer to handle dynamically added notifications
  const observer = new MutationObserver((mutations) => {
    mutations.forEach((mutation) => {
      mutation.addedNodes.forEach((node) => {
        if (node.classList && node.classList.contains('alert')) {
          setupNotification(node);
        }
      });
    });
  });

  const container = document.querySelector('.messages-container');
  if (container) {
    observer.observe(container, { childList: true });
  }
});