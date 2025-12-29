import Alpine from 'alpinejs';

let isInitialized = false;

declare global {
  interface Window {
    Alpine: typeof Alpine;
  }
}

// Only set window.Alpine if not already set to ensure singleton across bundles
if (!window.Alpine) {
  window.Alpine = Alpine;
}

// Use the global instance if available, otherwise fall back to the imported one
// This ensures that all bundles interact with the same Alpine instance (usually the one from the core bundle)
const AlpineSingleton = window.Alpine || Alpine;

export function initializeAlpine(): void {
  // Check if Alpine is already initialized
  // We check safe access to internal started property if available, or rely on our flag
  if (isInitialized) {
    return;
  }

  // If window.Alpine exists and it's already started (internal flag often used), skip
  // Note: Alpine doesn't expose a public 'started' property, so we rely on our mechanism
  // or safe idempotent start if possible.

  AlpineSingleton.start();
  isInitialized = true;
}

export function isAlpineInitialized(): boolean {
  return isInitialized;
}

export default AlpineSingleton;

