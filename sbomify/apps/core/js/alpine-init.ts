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
Alpine.plugin(morph);
Alpine.plugin(mask);
Alpine.plugin(persist);
Alpine.plugin(focus);
Alpine.plugin(intersect);
Alpine.plugin(collapse);
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


