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

function startLayoutInitialization() {
  initializeWorkspaceSelector();
  initializeModalFocusHandlers();
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
