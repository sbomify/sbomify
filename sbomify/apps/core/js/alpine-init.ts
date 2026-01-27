import Alpine from 'alpinejs';
import morph from '@alpinejs/morph';
import mask from '@alpinejs/mask';
import persist from '@alpinejs/persist';
import focus from '@alpinejs/focus';
import intersect from '@alpinejs/intersect';
import collapse from '@alpinejs/collapse';
import anchor from '@alpinejs/anchor';
import { parseJsonScript } from './utils';
import { registerWebSocketStore } from './components/websocket-store';

let initializationPromise: Promise<void> | null = null;

declare global {
  interface Window {
    Alpine: typeof Alpine;
    parseJsonScript: typeof parseJsonScript;
  }
}

/**
 * Alpine.js Plugin Registry
 * 
 * Registers all Alpine.js plugins used throughout the application:
 * - morph: Enables DOM morphing for smooth transitions when updating elements
 * - mask: Provides input masking for formatted inputs (phone numbers, dates, etc.)
 * - persist: Automatically persists Alpine.js data to localStorage
 * - focus: Enhances focus management and trap focus within modals/dropdowns
 * - intersect: Triggers callbacks when elements enter/exit the viewport
 * - collapse: Provides smooth collapse/expand animations for elements
 * - anchor: Enables smooth scrolling to anchor links
 */
Alpine.plugin(morph);
Alpine.plugin(mask);
Alpine.plugin(persist);
Alpine.plugin(focus);
Alpine.plugin(intersect);
Alpine.plugin(collapse);
Alpine.plugin(anchor);

// Register global stores before Alpine starts
registerWebSocketStore();

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


