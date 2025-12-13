import { copyToClipboard, initCopyButtons } from './clipboard';

// Expose clipboard functions globally
declare global {
  interface Window {
    copyToClipboard: typeof copyToClipboard;
    initCopyButtons: typeof initCopyButtons;
  }
}

window.copyToClipboard = copyToClipboard;
window.initCopyButtons = initCopyButtons;

// Auto-initialize copy buttons on DOMContentLoaded
document.addEventListener('DOMContentLoaded', () => {
  initCopyButtons();
});

// Re-initialize after HTMX content swaps
document.body.addEventListener('htmx:afterSwap', (event) => {
  const target = (event as CustomEvent).detail?.target;
  if (target instanceof HTMLElement) {
    initCopyButtons(target);
  }
});

export { copyToClipboard, initCopyButtons };
