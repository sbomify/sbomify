// Sentry must be initialized first
import { initSentry } from './sentry';
initSentry();

import 'vite/modulepreload-polyfill';
import './bootstrap-init';
// Navbar search and notifications modal moved to Alpine.js components

// Shared Chart.js setup (makes window.Chart available)
import './chart-setup';
import Alpine from 'alpinejs';
import './alerts-global';
import './clipboard-global';
import { eventBus, EVENTS } from './utils';

// Centralized Alpine components and HTMX lifecycle
import { registerAllComponents } from './alpine-components';
import { initHtmxLifecycle } from './htmx-lifecycle';
import { registerHtmxConfig } from './htmx-config';
import { initializeAlpine } from './alpine-init';

import '../../vulnerability_scanning/js/vulnerability-chart';

// Make globals available
declare global {
  interface Window {
    Alpine: typeof Alpine;
    bootstrap?: unknown; // Bootstrap JS removed, kept for backward compatibility
    eventBus: typeof eventBus;
    EVENTS: typeof EVENTS;
  }
}

// Bootstrap JS removed - using Alpine.js instead
// window.bootstrap kept as undefined for backward compatibility
window.eventBus = eventBus;
window.EVENTS = EVENTS;

// Register HTMX config
registerHtmxConfig();

// Register all Alpine components from central registry
registerAllComponents();

// Initialize centralized HTMX lifecycle handler
initHtmxLifecycle();

// Initialize HTMX-Alpine bridge for enhanced integration
import('./utils/htmx-alpine-bridge').then(({ initializeAlpineWithHTMX }) => {
  initializeAlpineWithHTMX();
}).catch(() => {
  // Bridge initialization is optional, continue without it
});

// Initialize Alpine
void initializeAlpine();

export { };
