// Initialize Feather icons
interface FeatherIcon {
  replace(): void;
}

declare var feather: FeatherIcon;

// Handle modal UX improvements
document.addEventListener('DOMContentLoaded', function() {
  console.log('[Modal] DOM Content Loaded');

  // Handle form submission on Enter for any form
  document.addEventListener('keypress', function(e: KeyboardEvent) {
    const activeElement = document.activeElement as HTMLElement;
    if (e.key === 'Enter' && !e.shiftKey && activeElement.tagName !== 'TEXTAREA') {
      const modalForm = (activeElement.closest('.modal') as HTMLElement)?.querySelector('form');
      if (modalForm && modalForm.contains(activeElement)) {
        console.log('[Modal] Enter key pressed in form, submitting');
        e.preventDefault();
        modalForm.submit();
      }
    }
  });

  // Track focus changes
  document.addEventListener('focusin', function(e) {
    console.log('[Focus] Focus changed to:', (e.target as HTMLElement).tagName, (e.target as HTMLElement).id);
  });

  // Initialize modals with custom focus management
  document.querySelectorAll('.modal').forEach(modalElement => {
    const modal = modalElement as HTMLElement;
    console.log('[Modal] Setting up modal:', modal.id);

    modal.addEventListener('show.bs.modal', () => {
      console.log('[Modal] Show event fired for:', modal.id);
    });

    modal.addEventListener('shown.bs.modal', () => {
      console.log('[Modal] Shown event fired for:', modal.id);
      console.log('[Modal] Current active element:', document.activeElement);

      const input = modal.querySelector('input[type="text"]') as HTMLInputElement;
      console.log('[Modal] Found input element:', input);

      if (input) {
        console.log('[Modal] Attempting to focus input');
        setTimeout(() => {
          input.focus();
          input.select();
          console.log('[Modal] Focus and select attempted. Active element is now:', document.activeElement);
          console.log('[Modal] Input selection:', input.selectionStart, input.selectionEnd);
        }, 50);
      }
    });

    modal.addEventListener('hide.bs.modal', () => {
      console.log('[Modal] Hide event fired for:', modal.id);
    });

    modal.addEventListener('hidden.bs.modal', () => {
      console.log('[Modal] Hidden event fired for:', modal.id);
    });
  });
});

// Initialize Feather icons
feather.replace();