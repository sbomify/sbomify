// Tailwind CSS (for public pages and Tailwind-themed components)
import '../../../assets/css/tailwind.src.css';

import '../../vulnerability_scanning/js/vulnerability-chart';
import './layout-interactions';
import './alerts-global';

// Centralized Alpine components and HTMX lifecycle
import { initHtmxLifecycle } from './htmx-lifecycle';
import { registerHtmxConfig } from './htmx-config';
import { registerMorphPreserve } from './htmx-morph-preserve';
import { initializeAlpine } from './alpine-init';
import { initDjangoMessages } from './django-messages';

// Register HTMX config
registerHtmxConfig();

// A morph swap that honours hx-preserve, for regions the server cannot
// re-render faithfully because the reader loaded part of them.
registerMorphPreserve();

// Initialize HTMX lifecycle handler
initHtmxLifecycle();

// Initialize Alpine
void initializeAlpine().then(initDjangoMessages);

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
