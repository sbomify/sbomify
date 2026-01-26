/**
 * HTMX Bundle - Application Entry Point
 * 
 * Global Setup File
 * 
 * This file sets up application-wide event handlers and initialization that
 * persist for the lifetime of the application. Event listeners added here are
 * intentionally global and do not require cleanup.
 * 
 * Global setup files vs Component-scoped:
 * - Global: Application-wide, persists for app lifetime, no cleanup needed
 * - Component-scoped: Per-component, requires destroy() cleanup
 */

// Bootstrap JS removed - using Alpine.js instead
// Bootstrap CSS still available for styling
// Chart.js removed - lazy loaded when needed via vulnerability-chart component
import './bootstrap-init';
import './alerts-global';
import './clipboard-global';
// Navbar search moved to Alpine.js component

// Centralized Alpine components and HTMX lifecycle
import { registerHtmxBundleComponents } from './alpine-components';
import { initHtmxLifecycle } from './htmx-lifecycle';
import { registerHtmxConfig } from './htmx-config';
import { initializeAlpine } from './alpine-init';

// Bootstrap JS removed - using Alpine.js instead
// window.bootstrap kept as undefined for backward compatibility
declare global {
    interface Window {
        bootstrap?: unknown;
    }
}

// Register HTMX config
registerHtmxConfig();

// Register all HTMX bundle components from central registry
registerHtmxBundleComponents();

// Initialize HTMX lifecycle handler
initHtmxLifecycle();

// Initialize Alpine
void initializeAlpine();

// Listen for successful document uploads and reload the page
window.addEventListener('document-uploaded', () => {
    setTimeout(() => {
        window.location.reload();
    }, 1500);
});

// Listen for successful SBOM uploads and reload the page
window.addEventListener('sbom-uploaded', () => {
    setTimeout(() => {
        window.location.reload();
    }, 1500);
});
