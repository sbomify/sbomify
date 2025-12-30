import Alpine from 'alpinejs';
import { parseJsonScript } from './utils';

let initializationPromise: Promise<void> | null = null;

declare global {
  interface Window {
    Alpine: typeof Alpine;
    parseJsonScript: typeof parseJsonScript;
  }
}

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

