import Alpine from 'alpinejs';

let isInitialized = false;

declare global {
  interface Window {
    Alpine: typeof Alpine;
  }
}

window.Alpine = Alpine;

export function initializeAlpine(): void {
  if (isInitialized) {
    return;
  }

  Alpine.start();
  isInitialized = true;
}

export function isAlpineInitialized(): boolean {
  return isInitialized;
}

export default Alpine;

