// Tailwind CSS (for public pages and Tailwind-themed components)
import '../../../assets/css/tailwind.src.css';

import './chart-setup';
import '../../vulnerability_scanning/js/vulnerability-chart';
import './layout-interactions';
import './alerts-global';
import './clipboard-global';
import './navbar-search';

// Centralized Alpine components and HTMX lifecycle
import { registerHtmxBundleComponents } from './alpine-components';
import { initHtmxLifecycle } from './htmx-lifecycle';
import { registerHtmxConfig } from './htmx-config';
import { initializeAlpine } from './alpine-init';

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
