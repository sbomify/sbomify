import Alpine from 'alpinejs';
import morph from '@alpinejs/morph';
import focus from '@alpinejs/focus';
import collapse from '@alpinejs/collapse';
import { parseJsonScript } from './utils';
import { formatNumber } from './number-format';
import { registerWebSocketStore } from './components/websocket-store';
import { registerOpenAssessmentsStore } from './components/open-assessments-store';
import { registerTooltipDirective } from './alpine-tooltip';
import { registerConfirmModal } from './components/confirm-modal';
import { registerAllComponents } from './alpine-components';

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
 * - focus: Enhances focus management and trap focus within modals/dropdowns
 * - collapse: Provides smooth collapse/expand animations for elements
 */
Alpine.plugin(morph);
Alpine.plugin(focus);
Alpine.plugin(collapse);

Alpine.magic('number', () => formatNumber);

// Register custom directives
registerTooltipDirective(Alpine);

// Register global stores before Alpine starts
registerWebSocketStore();

// Which assessment cards are open, kept out of the DOM so a refresh that
// morphs the artifact page cannot close them.
registerOpenAssessmentsStore();

// The base confirmation modal is available to every entry point.
registerConfirmModal();

if (!window.Alpine) {
  window.Alpine = Alpine;
}
window.parseJsonScript = parseJsonScript;

export function initializeAlpine(): Promise<void> {
  if (initializationPromise) {
    return initializationPromise;
  }

  initializationPromise = Promise.resolve().then(() => {
    // Any page bundle may reach startup first. Register shared components
    // here so the chrome never initializes against an incomplete registry.
    registerAllComponents();
    window.Alpine.start();
  });

  return initializationPromise;
}

export function isAlpineInitialized(): boolean {
  return initializationPromise !== null;
}

export default window.Alpine || Alpine;

