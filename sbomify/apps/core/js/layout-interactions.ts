declare module 'bootstrap';

import * as bootstrap from 'bootstrap';

declare global {
  interface Window {
    bootstrap: typeof bootstrap;
    __sbomifyLayoutInitialized?: boolean;
  }
}

const win = window as Window & { __sbomifyLayoutInitialized?: boolean };

/**
 * Workspace switching functionality
 */
function initializeWorkspaceSelector() {
  document.addEventListener('click', function(event) {
    const target = event.target as HTMLElement;
    const workspaceButton = target.closest('[data-workspace-key]') as HTMLElement;

    if (workspaceButton && workspaceButton.tagName === 'BUTTON') {
      const workspaceKey = workspaceButton.getAttribute('data-workspace-key');
      const workspaceName = workspaceButton.getAttribute('data-workspace-name');

      if (workspaceKey) {
        console.log('Switching to workspace:', workspaceName, 'Key:', workspaceKey);

        if (!/^[a-zA-Z0-9_-]+$/.test(workspaceKey)) {
          console.error('Invalid workspace key format:', workspaceKey);
          return;
        }

        const switchUrl = `/teams/switch/${encodeURIComponent(workspaceKey)}/`;
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

  const sidebarEl = sidebar;
  const mainEl = main;
  const sidebarToggleEl = sidebarToggle as HTMLElement;

  let sidebarOpen = false;

  function toggleSidebar() {
    sidebarOpen = !sidebarOpen;

    if (sidebarOpen) {
      sidebarEl.classList.add('sidebar-mobile-show');
      mainEl.classList.add('sidebar-mobile-show');
      sidebarToggleEl.setAttribute('aria-expanded', 'true');
      sidebarToggleEl.setAttribute('aria-label', 'Close navigation menu');

      const firstLink = sidebarEl.querySelector('.sidebar-link') as HTMLElement;
      if (firstLink) {
        firstLink.focus();
      }
    } else {
      sidebarEl.classList.remove('sidebar-mobile-show');
      mainEl.classList.remove('sidebar-mobile-show');
      sidebarToggleEl.setAttribute('aria-expanded', 'false');
      sidebarToggleEl.setAttribute('aria-label', 'Open navigation menu');
    }
  }

  function closeSidebar() {
    if (sidebarOpen) {
      sidebarOpen = false;
      sidebarEl.classList.remove('sidebar-mobile-show');
      mainEl.classList.remove('sidebar-mobile-show');
      sidebarToggleEl.setAttribute('aria-expanded', 'false');
      sidebarToggleEl.setAttribute('aria-label', 'Open navigation menu');
    }
  }

  sidebarToggleEl.addEventListener('click', function(e) {
    e.preventDefault();
    toggleSidebar();
  });

  if (sidebarClose) {
    sidebarClose.addEventListener('click', function(e) {
      e.preventDefault();
      closeSidebar();
    });
  }

  mainEl.addEventListener('click', function(e) {
    if (sidebarOpen && mainEl.classList.contains('sidebar-mobile-show')) {
      const target = e.target as HTMLElement;

      if (target === mainEl) {
        closeSidebar();
      }
    }
  });

  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape' && sidebarOpen) {
      closeSidebar();
      sidebarToggleEl.focus();
    }

    if ((e.ctrlKey || e.metaKey) && e.key === 'm') {
      e.preventDefault();
      toggleSidebar();
    }
  });

  window.addEventListener('resize', function() {
    if (window.innerWidth > 991.98 && sidebarOpen) {
      closeSidebar();
    }
  });

  let touchStartX = 0;
  let touchEndX = 0;

  document.addEventListener('touchstart', function(e) {
    touchStartX = e.changedTouches[0].screenX;
  }, { passive: true });

  document.addEventListener('touchend', function(e) {
    touchEndX = e.changedTouches[0].screenX;
    handleSwipe();
  }, { passive: true });

  function handleSwipe() {
    const swipeThreshold = 100;
    const swipeDistance = touchEndX - touchStartX;

    if (touchStartX < 50 && swipeDistance > swipeThreshold && !sidebarOpen) {
      toggleSidebar();
    }

    if (swipeDistance < -swipeThreshold && sidebarOpen) {
      closeSidebar();
    }
  }

  sidebarToggleEl.setAttribute('aria-expanded', 'false');
  sidebarToggleEl.setAttribute('aria-label', 'Open navigation menu');
  sidebarToggleEl.setAttribute('aria-controls', 'sidebar');

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

      switch (keyboardEvent.key) {
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

function initializeTooltips() {
  const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
  tooltipTriggerList.map((tooltipTriggerEl) => {
    return new bootstrap.Tooltip(tooltipTriggerEl);
  });
}

function initializeModalFocusHandlers() {
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
}

function startLayoutInitialization() {
  initializeWorkspaceSelector();
  initializeSidebar();
  initializeSidebarKeyboardNavigation();
  initializeTooltips();
  initializeModalFocusHandlers();
  console.log('Layout interactions initialized');
}

if (!win.__sbomifyLayoutInitialized) {
  win.__sbomifyLayoutInitialized = true;
  win.bootstrap = bootstrap;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', startLayoutInitialization, { once: true });
  } else {
    startLayoutInitialization();
  }
}

export {};
