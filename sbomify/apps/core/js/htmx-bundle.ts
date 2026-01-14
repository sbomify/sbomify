import * as bootstrap from 'bootstrap';
import './chart-setup'; // Shared Chart.js setup (includes window.Chart)
import '../../vulnerability_scanning/js/vulnerability-chart'; // Vulnerability chart logic
import './layout-interactions';
import './alerts-global';
import './clipboard-global';
import './navbar-search';

import { registerHtmxConfig } from './htmx-config';
import { registerDeleteModal } from './components/delete-modal';
import { registerWorkspaceSwitcher } from './components/workspace-switcher';
import { registerStandardCard } from './components/standard-card';
import { registerConfirmAction } from './components/confirm-action';
import { registerCopyToken } from './components/copy-token';
import { registerSiteNotifications } from './components/site-notifications';
import { registerPlanCard } from './components/plan-card';
import { registerEditableSingleField } from './components/editable-single-field';
import { registerProductIdentifiers } from './components/product-identifiers';
import { registerItemsListTable } from './components/items-list-table';
import { registerItemAssignmentManager } from './components/item-assignment-manager';
import { registerProductReleases } from './components/product-releases';
import { registerReleaseArtifacts } from './components/release-artifacts';
import { registerCopyableValue } from './components/copyable-value';
import { registerPublicStatusToggle } from './components/public-status-toggle';
import { registerAccessTokensList } from './components/access-tokens-list';
import { registerComponentMetaInfoEditor } from './component-meta-info-editor';
import { registerComponentMetaInfo } from './component-meta-info';
import { registerPlanSelection } from '../../billing/js/plan-selection';
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
registerHtmxConfig();
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
registerPlanSelection();
registerStandardCard();
registerConfirmAction();
registerCopyToken();
registerSiteNotifications();
registerPlanCard();
registerEditableSingleField();
registerProductIdentifiers();
registerItemsListTable();
registerItemAssignmentManager();
registerProductReleases();
registerReleaseArtifacts();

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
