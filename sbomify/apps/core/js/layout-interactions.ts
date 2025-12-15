declare module 'bootstrap';

import * as bootstrap from 'bootstrap';

declare global {
  interface Window {
    bootstrap: typeof bootstrap;
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

function initializeTooltips() {
  // Initialize tooltips with data-bs-toggle="tooltip" (but not on dropdown toggles)
  const tooltipTriggerList = document.querySelectorAll('[data-bs-toggle="tooltip"]');
  tooltipTriggerList.forEach((tooltipTriggerEl) => {
    const el = tooltipTriggerEl as HTMLElement;
    // Skip if this element is a dropdown toggle
    if (el.getAttribute('data-bs-toggle') === 'dropdown') {
      return;
    }

    const tooltip = new bootstrap.Tooltip(el, {
      trigger: 'hover focus',
    });

    // Hide tooltip on click (but don't prevent default behavior)
    el.addEventListener('click', () => {
      tooltip.hide();
    }, { passive: true });
  });

  // Initialize tooltips on elements with title attribute (but exclude dropdown toggles)
  const titleTooltipElements = document.querySelectorAll('[title]:not([data-bs-toggle="tooltip"])');
  titleTooltipElements.forEach((element) => {
    // Skip if this element is a dropdown toggle
    if (element.getAttribute('data-bs-toggle') === 'dropdown') {
      return;
    }

    // Only initialize if it's a button, link, or has a title and isn't already a tooltip
    if (element instanceof HTMLElement && element.title) {
      const tooltip = new bootstrap.Tooltip(element, {
        trigger: 'hover focus',
      });

      // Hide tooltip on click (but don't prevent default behavior)
      element.addEventListener('click', () => {
        tooltip.hide();
      }, { passive: true });

      // Hide tooltip on mouseleave (ensure it disappears when mouse moves away)
      element.addEventListener('mouseleave', () => {
        tooltip.hide();
      });
    }
  });

  // Special handling for dropdown toggles with tooltips - hide tooltip when dropdown opens/closes
  const dropdownToggles = document.querySelectorAll('[data-bs-toggle="dropdown"][title]');
  dropdownToggles.forEach((toggle) => {
    if (toggle instanceof HTMLElement && toggle.title) {
      const tooltip = new bootstrap.Tooltip(toggle, {
        trigger: 'hover focus',
      });

      // Hide tooltip when dropdown is shown or hidden
      toggle.addEventListener('show.bs.dropdown', () => {
        tooltip.hide();
      });

      toggle.addEventListener('shown.bs.dropdown', () => {
        tooltip.hide();
      });

      // Hide tooltip on mouseleave
      toggle.addEventListener('mouseleave', () => {
        tooltip.hide();
      });
    }
  });
}

function initializeDropdowns() {
  const dropdownToggles = document.querySelectorAll('[data-bs-toggle="dropdown"]');
  dropdownToggles.forEach((toggle) => {
    if (!bootstrap.Dropdown.getInstance(toggle)) {
      new bootstrap.Dropdown(toggle, {
        display: 'dynamic',
      });

      toggle.addEventListener('show.bs.dropdown', () => {
        const allToggles = document.querySelectorAll('[data-bs-toggle="dropdown"]');
        allToggles.forEach((otherToggle) => {
          if (otherToggle !== toggle) {
            const otherInstance = bootstrap.Dropdown.getInstance(otherToggle);
            if (otherInstance) {
              otherInstance.hide();
            }
          }
        });
      });

      toggle.addEventListener('shown.bs.dropdown', () => {
        toggle.setAttribute('aria-expanded', 'true');
      });

      toggle.addEventListener('hidden.bs.dropdown', () => {
        toggle.setAttribute('aria-expanded', 'false');
      });
    }
  });

  // Handle click outside to close dropdowns
  document.addEventListener('click', (event) => {
    const target = event.target as HTMLElement;
    const clickedDropdown = target.closest('.dropdown');
    const clickedToggle = target.closest('[data-bs-toggle="dropdown"]');
    const clickedDropdownItem = target.closest('.dropdown-item');
    
    // If clicked on a dropdown item, let Bootstrap handle it naturally
    if (clickedDropdownItem) {
      return;
    }
    
    // If clicked outside any dropdown, close all open dropdowns
    if (!clickedDropdown && !clickedToggle) {
      const allToggles = document.querySelectorAll('[data-bs-toggle="dropdown"]');
      allToggles.forEach((toggle) => {
        const dropdownInstance = bootstrap.Dropdown.getInstance(toggle);
        if (dropdownInstance) {
          const dropdownElement = toggle.closest('.dropdown');
          if (dropdownElement) {
            const dropdownMenu = dropdownElement.querySelector('.dropdown-menu');
            if (dropdownMenu && dropdownMenu.classList.contains('show')) {
              dropdownInstance.hide();
            }
          }
        }
      });
    }
  });

  // Handle Escape key to close dropdowns
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      const allToggles = document.querySelectorAll('[data-bs-toggle="dropdown"]');
      allToggles.forEach((toggle) => {
        const dropdownInstance = bootstrap.Dropdown.getInstance(toggle);
        if (dropdownInstance) {
          const dropdownElement = toggle.closest('.dropdown');
          if (dropdownElement) {
            const dropdownMenu = dropdownElement.querySelector('.dropdown-menu');
            if (dropdownMenu && dropdownMenu.classList.contains('show')) {
              dropdownInstance.hide();
              (toggle as HTMLElement).focus();
            }
          }
        }
      });
    }
  });
}

function initializeDropdownAriaState() {
  document.addEventListener('hidden.bs.dropdown', (event) => {
    const target = event.target as HTMLElement;
    let toggle: HTMLElement | null = null;

    if (target.getAttribute('data-bs-toggle') === 'dropdown') {
      toggle = target;
    } else {
      toggle = target.querySelector('[data-bs-toggle="dropdown"]') as HTMLElement;
    }

    if (toggle) {
      toggle.setAttribute('aria-expanded', 'false');
      toggle.blur();
    }
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
  initializeDropdowns();
  initializeDropdownAriaState();
  initializeModalFocusHandlers();
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

export { };
