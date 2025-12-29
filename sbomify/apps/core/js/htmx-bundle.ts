import * as bootstrap from 'bootstrap';
import './layout-interactions';
import './alerts-global';
import './clipboard-global';
import './navbar-search';
import { registerDeleteModal } from './components/delete-modal';
import { registerWorkspaceSwitcher } from './components/workspace-switcher';
import { registerCopyableValue } from './components/copyable-value';
import { registerPublicStatusToggle } from './components/public-status-toggle';
import { registerSbomUpload } from '../../sboms/js/sbom-upload';
import { registerDocumentUpload } from '../../documents/js/document-upload';
import { initializeAlpine } from './alpine-init';

registerCopyableValue();
registerPublicStatusToggle();
registerWorkspaceSwitcher();
registerSbomUpload();
registerDocumentUpload();
registerDeleteModal();

initializeAlpine();

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

// Expose bootstrap globally
declare global {
    interface Window {
        bootstrap: typeof bootstrap;
    }
}

window.bootstrap = bootstrap;
