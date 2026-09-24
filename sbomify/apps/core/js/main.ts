// Sentry must be initialized first
import { initSentry } from './sentry';
initSentry();

// Initialize theme manager early (before Alpine)
import { initThemeManager } from './theme-manager';
initThemeManager();

import './layout-interactions';
import './notifications-modal';

// Shared Chart.js setup (makes window.Chart available)
import './chart-setup';
import Alpine from 'alpinejs';
import './alerts-global';
import './clipboard-global';
import {
  eventBus,
  EVENTS,
  formatDate,
  formatDateTime,
  formatRelativeDate,
  formatCompactRelativeDate,
} from './utils';

// Centralized Alpine components and HTMX lifecycle
import { initHtmxLifecycle } from './htmx-lifecycle';
import { registerHtmxConfig } from './htmx-config';
import { initializeAlpine } from './alpine-init';
import { initDjangoMessages } from './django-messages';

// Make globals available
declare global {
  interface Window {
    Alpine: typeof Alpine;
    eventBus: typeof eventBus;
    EVENTS: typeof EVENTS;
    sbomifyFormatDate: typeof formatDate;
    sbomifyFormatDateTime: typeof formatDateTime;
    sbomifyFormatRelativeDate: typeof formatRelativeDate;
    sbomifyFormatCompactRelativeDate: typeof formatCompactRelativeDate;
  }
}

window.eventBus = eventBus;
window.EVENTS = EVENTS;
window.sbomifyFormatDate = formatDate;
window.sbomifyFormatDateTime = formatDateTime;
window.sbomifyFormatRelativeDate = formatRelativeDate;
window.sbomifyFormatCompactRelativeDate = formatCompactRelativeDate;

// Register HTMX config
registerHtmxConfig();

// Initialize centralized HTMX lifecycle handler
initHtmxLifecycle();

// Initialize Alpine
void initializeAlpine().then(initDjangoMessages);

export { };
