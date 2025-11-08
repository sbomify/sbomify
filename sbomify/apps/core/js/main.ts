import 'vite/modulepreload-polyfill';

// Type declaration for bootstrap module (avoids needing @types/bootstrap in production)
declare module 'bootstrap';

// Bootstrap JS - make available globally for Vue components
import * as bootstrap from 'bootstrap';

// Extend the Window interface to include bootstrap
declare global {
  interface Window {
    bootstrap: typeof bootstrap;
  }
}

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
      const workspaceName = workspaceButton.getAttribute('data-workspace-name');

      if (workspaceKey) {
        console.log('Switching to workspace:', workspaceName, 'Key:', workspaceKey);

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

        console.log('Redirecting to:', targetUrl);
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

  console.log('Sidebar functionality initialized');
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

  console.log('Sidebar keyboard navigation initialized');
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

  console.log('Main.ts loaded successfully - all components initialized');
});

// Import Vue component mounting utility
import mountVueComponent from './common_vue';
import './alerts-global'; // Ensure alerts are available globally
import { eventBus, EVENTS } from './utils';
import EditableSingleField from './components/EditableSingleField.vue';
import CopyableValue from './components/CopyableValue.vue';
import ConfirmAction from './components/ConfirmAction.vue';
import CopyToken from './components/CopyToken.vue';
import SiteNotifications from './components/SiteNotifications.vue';
import StandardCard from './components/StandardCard.vue';
import PlanCard from './components/PlanCard.vue';
import AccessTokensList from './components/AccessTokensList.vue';
import PublicStatusToggle from './components/PublicStatusToggle.vue';
import ComponentMetaInfo from './components/ComponentMetaInfo.vue';
import ComponentMetaInfoEditor from './components/ComponentMetaInfoEditor.vue';
import ComponentMetaInfoDisplay from './components/ComponentMetaInfoDisplay.vue';
import DangerZone from './components/DangerZone.vue';
import ProjectDangerZone from './components/ProjectDangerZone.vue';
import ProductDangerZone from './components/ProductDangerZone.vue';
import ExportDataCard from './components/ExportDataCard.vue';
import ItemAssignmentManager from './components/ItemAssignmentManager.vue';
import ItemsListTable from './components/ItemsListTable.vue';
import PublicCard from './components/PublicCard.vue';
import PublicPageLayout from './components/PublicPageLayout.vue';
import PublicProjectComponents from './components/PublicProjectComponents.vue';
import PublicProductProjects from './components/PublicProductProjects.vue';
import PublicDownloadCard from './components/PublicDownloadCard.vue';
import ProductIdentifiers from './components/ProductIdentifiers.vue';
import ProductLinks from './components/ProductLinks.vue';
import ProductReleases from './components/ProductReleases.vue';
import ReleaseArtifacts from './components/ReleaseArtifacts.vue';
import ReleaseDangerZone from './components/ReleaseDangerZone.vue';
import PublicReleaseArtifacts from './components/PublicReleaseArtifacts.vue';

import ReleaseList from './components/ReleaseList.vue';

// Initialize Vue components
mountVueComponent('vc-editable-single-field', EditableSingleField);
mountVueComponent('vc-copyable-value', CopyableValue);
mountVueComponent('vc-confirm-action', ConfirmAction);
mountVueComponent('vc-copy-token', CopyToken);
mountVueComponent('vc-site-notifications', SiteNotifications);
mountVueComponent('vc-standard-card', StandardCard);
mountVueComponent('vc-plan-card', PlanCard);
mountVueComponent('vc-access-tokens-list', AccessTokensList);
mountVueComponent('vc-public-status-toggle', PublicStatusToggle);
mountVueComponent('vc-component-meta-info', ComponentMetaInfo);
mountVueComponent('vc-component-meta-info-editor', ComponentMetaInfoEditor);
mountVueComponent('vc-component-meta-info-display', ComponentMetaInfoDisplay);
mountVueComponent('vc-danger-zone', DangerZone);
mountVueComponent('vc-project-danger-zone', ProjectDangerZone);
mountVueComponent('vc-product-danger-zone', ProductDangerZone);
mountVueComponent('vc-export-data-card', ExportDataCard);
mountVueComponent('vc-item-assignment-manager', ItemAssignmentManager);
mountVueComponent('vc-items-list-table', ItemsListTable);
mountVueComponent('vc-public-card', PublicCard);
mountVueComponent('vc-public-page-layout', PublicPageLayout);
mountVueComponent('vc-public-project-components', PublicProjectComponents);
mountVueComponent('vc-public-product-projects', PublicProductProjects);
mountVueComponent('vc-public-download-card', PublicDownloadCard);
mountVueComponent('vc-product-identifiers', ProductIdentifiers);
mountVueComponent('vc-product-links', ProductLinks);
mountVueComponent('vc-product-releases', ProductReleases);
mountVueComponent('vc-release-artifacts', ReleaseArtifacts);
mountVueComponent('vc-release-danger-zone', ReleaseDangerZone);
mountVueComponent('vc-public-release-artifacts', PublicReleaseArtifacts);

mountVueComponent('vc-release-list', ReleaseList);

// Declare global variables
declare global {
  interface Window {
    eventBus: typeof eventBus;
    EVENTS: typeof EVENTS;
  }
}

// Make eventBus available globally for inline scripts
window.eventBus = eventBus;
window.EVENTS = EVENTS;

// Export something to make TypeScript happy
export {};
