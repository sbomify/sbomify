import * as bootstrap from 'bootstrap';
import './chart-setup'; // Shared Chart.js setup (includes window.Chart)
import '../../vulnerability_scanning/js/vulnerability-chart'; // Vulnerability chart logic
import './layout-interactions';
import './alerts-global';
import './clipboard-global';
import './navbar-search';

import { registerDeleteModal } from './components/delete-modal';
import { registerWorkspaceSwitcher } from './components/workspace-switcher';
import { registerCopyableValue } from './components/copyable-value';
import { registerPublicStatusToggle } from './components/public-status-toggle';
import { registerAccessTokensList } from './components/access-tokens-list';
import { registerComponentMetaInfoEditor } from './component-meta-info-editor';
import { registerComponentMetaInfo } from './component-meta-info';
import { initializeAlpine } from './alpine-init';

import { registerSbomUpload } from '../../sboms/js/sbom-upload';
import { registerSbomsTable } from '../../sboms/js/sboms-table';
import { registerCiCdInfo } from '../../sboms/js/ci-cd-info';
import { registerLicensesEditor } from '../../sboms/js/licenses-editor';
import { registerContactsEditor } from '../../sboms/js/contacts-editor';
import { registerSupplierEditor } from '../../sboms/js/supplier-editor';
import { registerDocumentUpload } from '../../documents/js/document-upload';

// Expose bootstrap globally
declare global {
    interface Window {
        bootstrap: typeof bootstrap;
    }
}

window.bootstrap = bootstrap;

// Register all components
registerCopyableValue();
registerPublicStatusToggle();
registerWorkspaceSwitcher();
registerAccessTokensList();
registerSbomUpload();
registerSbomsTable();
registerDocumentUpload();
registerCiCdInfo();
registerComponentMetaInfoEditor();
registerComponentMetaInfo();
registerLicensesEditor();
registerContactsEditor();
registerSupplierEditor();
registerDeleteModal();

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
