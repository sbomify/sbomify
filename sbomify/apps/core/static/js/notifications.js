/**
 * Notifications Auto-Dismiss
 * 
 * This file is deprecated - notifications now use Alpine.js notificationAutoDismiss component
 * Kept for backward compatibility but functionality moved to Alpine
 * 
 * For new notifications, use x-data="notificationAutoDismiss(4000)" on alert elements
 */
document.addEventListener('DOMContentLoaded', function() {
  // Alpine.js handles notification auto-dismiss via notificationAutoDismiss component
  // This file is kept for backward compatibility but no longer initializes Bootstrap alerts
  
  // If Alpine is not available, fallback to basic behavior
  if (typeof window.Alpine === 'undefined') {
    console.warn('Alpine.js not available - notification auto-dismiss may not work');
  }
});