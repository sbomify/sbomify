// Bootstrap removed - using Alpine.js for tooltips, dropdowns, and modals

declare global {
  interface Window {
    __sbomifyLayoutInitialized?: boolean;
  }
}

const win = window as Window & { __sbomifyLayoutInitialized?: boolean };

function initializeWorkspaceSelector() {
  document.addEventListener('click', function (event) {
    const target = event.target as HTMLElement;
    const workspaceButton = target.closest('[data-workspace-key]') as HTMLElement;

    if (workspaceButton && workspaceButton.tagName === 'BUTTON') {
      const workspaceKey = workspaceButton.getAttribute('data-workspace-key');

      if (workspaceKey) {
        if (!/^[a-zA-Z0-9_-]+$/.test(workspaceKey)) {
          return;
        }

        const switchUrl = `/workspaces/switch/${encodeURIComponent(workspaceKey)}/`;
        const currentPath = window.location.pathname;
        const targetUrl = `${switchUrl}?next=${encodeURIComponent(currentPath)}`;
        window.location.href = targetUrl;
      }
    }
  });
}

function initializeSidebar() {
  const sidebar = document.getElementById('sidebar');
  const main = document.querySelector('.main');
  const sidebarToggle = document.querySelector('.js-sidebar-toggle');
  const sidebarClose = document.querySelector('.js-sidebar-close');

  if (!sidebar || !main || !sidebarToggle) {
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

  sidebarToggleEl.addEventListener('click', function (e) {
    e.preventDefault();
    toggleSidebar();
  });

  if (sidebarClose) {
    sidebarClose.addEventListener('click', function (e) {
      e.preventDefault();
      closeSidebar();
    });
  }

  mainEl.addEventListener('click', function (e) {
    if (sidebarOpen && mainEl.classList.contains('sidebar-mobile-show')) {
      const target = e.target as HTMLElement;

      if (target === mainEl) {
        closeSidebar();
      }
    }
  });

  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && sidebarOpen) {
      closeSidebar();
      sidebarToggleEl.focus();
    }

    if ((e.ctrlKey || e.metaKey) && e.key === 'm') {
      e.preventDefault();
      toggleSidebar();
    }
  });

  window.addEventListener('resize', function () {
    if (window.innerWidth > 991.98 && sidebarOpen) {
      closeSidebar();
    }
  });

  let touchStartX = 0;
  let touchEndX = 0;

  document.addEventListener('touchstart', function (e) {
    touchStartX = e.changedTouches[0].screenX;
  }, { passive: true });

  document.addEventListener('touchend', function (e) {
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
}

/**
 * Enhanced keyboard navigation for sidebar
 */
function initializeSidebarKeyboardNavigation() {
  const sidebar = document.getElementById('sidebar');
  if (!sidebar) return;

  const sidebarLinks = sidebar.querySelectorAll('.sidebar-link');

  sidebarLinks.forEach((link, index) => {
    link.addEventListener('keydown', function (e) {
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
}

// Bootstrap tooltip, dropdown, and aria state functions removed - now using Alpine.js

/**
 * Auto-focus first text input when modals are shown.
 * Listens for custom 'modal-shown' events dispatched by Alpine.js modal components.
 */
function initializeModalFocusHandlers() {
  // Listen for custom modal-shown event (dispatched by Alpine.js modals)
  document.addEventListener('modal-shown', (e: Event) => {
    const customEvent = e as CustomEvent<{ modalId?: string }>;
    const modalId = customEvent.detail?.modalId;

    if (modalId) {
      const modal = document.getElementById(modalId);
      if (modal) {
        focusFirstInput(modal);
      }
    }
  });

  // Also handle legacy Bootstrap modal events during transition period
  document.querySelectorAll('.modal').forEach(modalElement => {
    const modal = modalElement as HTMLElement;
    modal.addEventListener('shown.bs.modal', () => focusFirstInput(modal));
  });
}

function focusFirstInput(modal: HTMLElement): void {
  const input = modal.querySelector('input[type="text"], input[type="email"], input[type="password"], textarea') as HTMLInputElement | HTMLTextAreaElement;
  if (input) {
    setTimeout(() => {
      input.focus();
      input.select();
    }, 50);
  }
}

/**
 * Initialize Cmd+K / Ctrl+K keyboard shortcut to focus search
 */
function initializeSearchShortcut() {
  document.addEventListener('keydown', (e) => {
    // Check for Cmd+K (Mac) or Ctrl+K (Windows/Linux)
    if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
      e.preventDefault();

      const searchInput = document.getElementById('navbar-search-input') as HTMLInputElement;
      if (searchInput) {
        searchInput.focus();
        searchInput.select();
      }
    }
  });
}

function startLayoutInitialization() {
  initializeWorkspaceSelector();
  initializeSidebar();
  initializeSidebarKeyboardNavigation();
  initializeModalFocusHandlers();
  initializeSearchShortcut();
}

if (!win.__sbomifyLayoutInitialized) {
  win.__sbomifyLayoutInitialized = true;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', startLayoutInitialization, { once: true });
  } else {
    startLayoutInitialization();
  }
}

export { };
