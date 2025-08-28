import 'vite/modulepreload-polyfill';



// Type declaration for bootstrap module (avoids needing @types/bootstrap in production)
declare module 'bootstrap';

// Bootstrap JS - make available globally for Vue components
import * as bootstrap from 'bootstrap';

// Bootstrap is handled by django-components.ts global declaration

window.bootstrap = bootstrap;


// Chart.js - make available globally for admin dashboard
import {
  Chart,
  CategoryScale,
  LinearScale,
  BarElement,
  Title,
  Tooltip,
  Legend,
} from 'chart.js';

// Register Chart.js components
Chart.register(
  CategoryScale,
  LinearScale,
  BarElement,
  Title,
  Tooltip,
  Legend
);

// Make Chart available globally
declare global {
  interface Window {
    Chart: typeof Chart;
  }
}

window.Chart = Chart;

/**
 * Workspace switching functionality
 */
function initializeWorkspaceSelector() {
  // Handle workspace dropdown button clicks
  document.addEventListener('click', function(event) {
    const target = event.target as HTMLElement;
    const workspaceButton = target.closest('[data-workspace-key]') as HTMLElement;

    if (workspaceButton && workspaceButton.tagName === 'BUTTON') {
      const workspaceKey = workspaceButton.getAttribute('data-workspace-key');

      if (workspaceKey) {


        // Validate workspaceKey to ensure it matches the expected pattern (e.g., ^[a-zA-Z0-9_-]+$)
        if (!/^[a-zA-Z0-9_-]+$/.test(workspaceKey)) {
          console.error('Invalid workspace key format:', workspaceKey);
          return;
        }

        // Construct the team switch URL - matches the URL pattern from teams/urls.py
        const switchUrl = `/teams/switch/${encodeURIComponent(workspaceKey)}/`;

        // Get current view name for preserving context
        const currentPath = window.location.pathname;
        const targetUrl = `${switchUrl}?next=${encodeURIComponent(currentPath)}`;


        window.location.href = targetUrl;
      }
    }
  });
}

/**
 * Sidebar functionality with enhanced mobile and keyboard support
 */
function initializeSidebar() {
  const sidebar = document.getElementById('sidebar');
  const main = document.querySelector('.main');
  const sidebarToggle = document.querySelector('.js-sidebar-toggle');
  const sidebarClose = document.querySelector('.js-sidebar-close');

  if (!sidebar || !main || !sidebarToggle) {
    console.warn('Sidebar elements not found');
    return;
  }

  let sidebarOpen = false;

    // Function to toggle sidebar
  function toggleSidebar() {
    sidebarOpen = !sidebarOpen;

    if (sidebarOpen) {
      sidebar!.classList.add('sidebar-mobile-show');
      main!.classList.add('sidebar-mobile-show');
      sidebarToggle!.setAttribute('aria-expanded', 'true');
      sidebarToggle!.setAttribute('aria-label', 'Close navigation menu');

      // Focus first link in sidebar for accessibility
      const firstLink = sidebar!.querySelector('.sidebar-link') as HTMLElement;
      if (firstLink) {
        firstLink.focus();
      }
    } else {
      sidebar!.classList.remove('sidebar-mobile-show');
      main!.classList.remove('sidebar-mobile-show');
      sidebarToggle!.setAttribute('aria-expanded', 'false');
      sidebarToggle!.setAttribute('aria-label', 'Open navigation menu');
    }
  }

  // Function to close sidebar
  function closeSidebar() {
    if (sidebarOpen) {
      sidebarOpen = false;
      sidebar!.classList.remove('sidebar-mobile-show');
      main!.classList.remove('sidebar-mobile-show');
      sidebarToggle!.setAttribute('aria-expanded', 'false');
      sidebarToggle!.setAttribute('aria-label', 'Open navigation menu');
    }
  }

  // Toggle button click handler
  sidebarToggle.addEventListener('click', function(e) {
    e.preventDefault();
    toggleSidebar();
  });

  // Close button click handler (if present)
  if (sidebarClose) {
    sidebarClose.addEventListener('click', function(e) {
      e.preventDefault();
      closeSidebar();
    });
  }

  // Close sidebar when clicking overlay
  main.addEventListener('click', function(e) {
    if (sidebarOpen && main.classList.contains('sidebar-mobile-show')) {
      const target = e.target as HTMLElement;

      // Check if click is on the overlay (::before pseudo-element area)
      if (target === main) {
        closeSidebar();
      }
    }
  });

  // Keyboard navigation
  document.addEventListener('keydown', function(e) {
    // ESC key closes sidebar
    if (e.key === 'Escape' && sidebarOpen) {
      closeSidebar();
      (sidebarToggle as HTMLElement).focus();
    }

    // Ctrl+M or Cmd+M toggles sidebar (like many code editors)
    if ((e.ctrlKey || e.metaKey) && e.key === 'm') {
      e.preventDefault();
      toggleSidebar();
    }
  });

  // Handle window resize
  window.addEventListener('resize', function() {
    // Close sidebar on larger screens
    if (window.innerWidth > 991.98 && sidebarOpen) {
      closeSidebar();
    }
  });

  // Touch/swipe support
  let touchStartX = 0;
  let touchEndX = 0;

  // Touch start
  document.addEventListener('touchstart', function(e) {
    touchStartX = e.changedTouches[0].screenX;
  }, { passive: true });

  // Touch end
  document.addEventListener('touchend', function(e) {
    touchEndX = e.changedTouches[0].screenX;
    handleSwipe();
  }, { passive: true });

  function handleSwipe() {
    const swipeThreshold = 100;
    const swipeDistance = touchEndX - touchStartX;

    // Swipe right from left edge to open sidebar
    if (touchStartX < 50 && swipeDistance > swipeThreshold && !sidebarOpen) {
      toggleSidebar();
    }

    // Swipe left to close sidebar when open
    if (swipeDistance < -swipeThreshold && sidebarOpen) {
      closeSidebar();
    }
  }

  // Initialize ARIA attributes
  sidebarToggle.setAttribute('aria-expanded', 'false');
  sidebarToggle.setAttribute('aria-label', 'Open navigation menu');
  sidebarToggle.setAttribute('aria-controls', 'sidebar');


}

/**
 * Enhanced keyboard navigation for sidebar
 */
function initializeSidebarKeyboardNavigation() {
  const sidebar = document.getElementById('sidebar');
  if (!sidebar) return;

  const sidebarLinks = sidebar.querySelectorAll('.sidebar-link');

  sidebarLinks.forEach((link, index) => {
    link.addEventListener('keydown', function(e) {
      const keyboardEvent = e as KeyboardEvent;
      const currentIndex = index;
      let targetIndex = -1;

      switch(keyboardEvent.key) {
        case 'ArrowDown':
          keyboardEvent.preventDefault();
          targetIndex = currentIndex + 1;
          break;
        case 'ArrowUp':
          keyboardEvent.preventDefault();
          targetIndex = currentIndex - 1;
          break;
        case 'Home':
          keyboardEvent.preventDefault();
          targetIndex = 0;
          break;
        case 'End':
          keyboardEvent.preventDefault();
          targetIndex = sidebarLinks.length - 1;
          break;
      }

      if (targetIndex >= 0 && targetIndex < sidebarLinks.length) {
        (sidebarLinks[targetIndex] as HTMLElement).focus();
      }
    });
  });


}

/**
 * Initialize delete modal handlers for reusable delete confirmation modals
 */
function initializeDeleteModals() {
  // Find all modals that have the pattern *Modal (like deleteTokenModal)
  const deleteModals = document.querySelectorAll('[id$="Modal"]');

  deleteModals.forEach(modal => {
    modal.addEventListener('show.bs.modal', function(event) {
      const button = event.relatedTarget as HTMLElement;
      if (!button) return;

      const itemName = button.getAttribute('data-item-name');
      const deleteUrl = button.getAttribute('data-delete-url');

      // Update modal content
      const itemNameElement = document.getElementById(`${modal.id}ItemName`);
      if (itemNameElement && itemName) {
        itemNameElement.textContent = itemName;
      }

      // Update form action
      const form = document.getElementById(`${modal.id}Form`) as HTMLFormElement;
      if (form && deleteUrl) {
        form.action = deleteUrl;
      }
    });
  });
}

/**
 * Initialize custom components
 */
document.addEventListener('DOMContentLoaded', function() {
  // Initialize workspace selector
  initializeWorkspaceSelector();

  // Initialize sidebar functionality
  initializeSidebar();
  initializeSidebarKeyboardNavigation();

  // Initialize Bootstrap tooltips
  const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
  tooltipTriggerList.map((tooltipTriggerEl) => {
    return new bootstrap.Tooltip(tooltipTriggerEl);
  });

  // Initialize Bootstrap 5 toast notifications
  NotificationManager.initialize();

  // Handle modal UX improvements
  document.querySelectorAll('.modal').forEach(modalElement => {
    const modal = modalElement as HTMLElement;

    modal.addEventListener('shown.bs.modal', () => {
      const input = modal.querySelector('input[type="text"]') as HTMLInputElement;
      if (input) {
        setTimeout(() => {
          input.focus();
          input.select();
        }, 50);
      }
    });
  });

  // Initialize delete modal handlers
  initializeDeleteModals();


});

// Keep alerts available globally for Django templates
import './alerts-global';

// Import eventBus for TypeScript compilation (even though we don't mount Vue)
import { eventBus, EVENTS } from './utils';



// Import Django template component functionality
import './utils/django-components';
import { NotificationManager } from './utils/django-components';
import './components/releases-crud';
import './components/release-crud-modal';
import './components/release-artifacts-table';
import './components/danger-zone';
import './components/product-links-crud';
import './components/product-identifiers-crud';
import './components/public-status-toggle';
import './components/editable-field';
import './components/assignment-manager';

import './components/UserSettingsPage';


// Declare global variables for TypeScript
declare global {
  interface Window {
    eventBus: typeof eventBus;
    EVENTS: typeof EVENTS;
  }
}

// Make eventBus available globally (for any remaining TypeScript compilation)
window.eventBus = eventBus;
window.EVENTS = EVENTS;

// Export something to make TypeScript happy
export {};