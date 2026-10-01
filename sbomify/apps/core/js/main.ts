// Sentry must be initialized first
import { initSentry } from './sentry';
initSentry();

// Initialize theme manager early (before Alpine)
import { initThemeManager } from './theme-manager';
initThemeManager();

import './notifications-modal';

import Alpine from 'alpinejs';
import './alerts-global';
import { formatDate } from './utils';

// Centralized Alpine components and HTMX lifecycle
import { initHtmxLifecycle } from './htmx-lifecycle';
import { registerHtmxConfig } from './htmx-config';
import { initializeAlpine } from './alpine-init';
import { initDjangoMessages } from './django-messages';

// Make globals available
declare global {
  interface Window {
    Alpine: typeof Alpine;
    sbomifyFormatDate: typeof formatDate;
  }
}

window.sbomifyFormatDate = formatDate;

// Register HTMX config
registerHtmxConfig();

// Initialize centralized HTMX lifecycle handler
initHtmxLifecycle();

// Initialize Alpine
void initializeAlpine().then(initDjangoMessages);

export { };
