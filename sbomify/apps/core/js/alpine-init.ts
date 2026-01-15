import Alpine from 'alpinejs';
import morph from '@alpinejs/morph';
import mask from '@alpinejs/mask';
import persist from '@alpinejs/persist';
import focus from '@alpinejs/focus';
import intersect from '@alpinejs/intersect';
import collapse from '@alpinejs/collapse';
import anchor from '@alpinejs/anchor';
import { parseJsonScript } from './utils';

let initializationPromise: Promise<void> | null = null;

declare global {
  interface Window {
    Alpine: typeof Alpine;
    parseJsonScript: typeof parseJsonScript;
  }
}

// Register plugins
// morph: Enables DOM morphing for smooth transitions when updating elements
Alpine.plugin(morph);
// mask: Provides input masking for formatted inputs (phone numbers, dates, etc.)
Alpine.plugin(mask);
// persist: Automatically persists Alpine.js data to localStorage
Alpine.plugin(persist);
// focus: Enhances focus management and trap focus within modals/dropdowns
Alpine.plugin(focus);
// intersect: Triggers callbacks when elements enter/exit the viewport
Alpine.plugin(intersect);
// collapse: Provides smooth collapse/expand animations for elements
Alpine.plugin(collapse);
// anchor: Enables smooth scrolling to anchor links
Alpine.plugin(anchor);

if (!window.Alpine) {
  window.Alpine = Alpine;
}
window.parseJsonScript = parseJsonScript;

export function initializeAlpine(): Promise<void> {
  if (initializationPromise) {
    return initializationPromise;
  }

  initializationPromise = Promise.resolve().then(() => {
    window.Alpine.start();
  });

  return initializationPromise;
}

export function isAlpineInitialized(): boolean {
  return initializationPromise !== null;
}

export default window.Alpine || Alpine;


