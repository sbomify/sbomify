// Sentry must be initialized first
import { initSentry } from './sentry';
initSentry();

// Initialize theme manager early (before Alpine)
import { initThemeManager } from './theme-manager';
initThemeManager();

// Tailwind CSS (for tw_base / Tailwind-themed pages)
import '../../../static/css/tailwind.src.css';

import 'vite/modulepreload-polyfill';
import './layout-interactions';
import './navbar-search';
import './notifications-modal';

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
    eventBus: typeof eventBus;
    EVENTS: typeof EVENTS;
  }
}

window.eventBus = eventBus;
window.EVENTS = EVENTS;

// Register HTMX config
registerHtmxConfig();

// Register all Alpine components from central registry
registerAllComponents();

// Initialize centralized HTMX lifecycle handler
initHtmxLifecycle();

// Initialize Alpine
void initializeAlpine();

export { };
