import 'vite/modulepreload-polyfill';
import './layout-interactions';
import './navbar-search';
import './notifications-modal';

// Shared Chart.js setup (makes window.Chart available)
import './chart-setup';
import * as bootstrap from 'bootstrap';
import Alpine from 'alpinejs';
import './alerts-global'; // Ensure alerts are available globally
import './clipboard-global'; // Clipboard utilities with auto-initialization
import { eventBus, EVENTS } from './utils';

import { registerCopyableValue } from './components/copyable-value';
import { registerPublicStatusToggle } from './components/public-status-toggle';
import { registerWorkspaceSwitcher } from './components/workspace-switcher';
import { registerAccessTokensList } from './components/access-tokens-list';
import { registerDeleteModal } from './components/delete-modal';
import { registerReleaseList } from './components/release-list';
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
import { registerProductIdentifiersBarcodes } from './components/product-identifiers-barcodes';
import { registerAssessmentBadge } from '../../plugins/js/assessment-badge';
import { registerComponentMetaInfoEditor } from './component-meta-info-editor';
import { registerComponentMetaInfo } from './component-meta-info';
import { registerPlanSelection } from '../../billing/js/plan-selection'; // Import billing plan selection logic
import { initializeAlpine } from './alpine-init';

import { registerSbomUpload } from '../../sboms/js/sbom-upload';
import { registerCiCdInfo } from '../../sboms/js/ci-cd-info';
import { registerContactsEditor } from '../../sboms/js/contacts-editor';
import { registerSupplierEditor } from '../../sboms/js/supplier-editor';
import { registerLicensesEditor } from '../../sboms/js/licenses-editor';
import { registerDocumentUpload } from '../../documents/js/document-upload';
import { registerSbomsTable } from '../../sboms/js/sboms-table';

import '../../vulnerability_scanning/js/vulnerability-chart';


// Make globals available
declare global {
  interface Window {
    Alpine: typeof Alpine;
    bootstrap: typeof bootstrap;
    eventBus: typeof eventBus;
    EVENTS: typeof EVENTS;
  }
}

window.bootstrap = bootstrap;
window.eventBus = eventBus;
window.EVENTS = EVENTS;

// Register components
registerCopyableValue();
registerPublicStatusToggle();
registerWorkspaceSwitcher();
registerAccessTokensList();
registerSbomUpload();
registerCiCdInfo();
registerContactsEditor();
registerSupplierEditor();
registerLicensesEditor();
registerReleaseList();
registerProductIdentifiersBarcodes();
registerAssessmentBadge();
registerDocumentUpload();
registerDeleteModal();
registerSbomsTable();
registerComponentMetaInfoEditor();
registerComponentMetaInfo();
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

// Initialize Alpine
void initializeAlpine();


// Global HTMX event handler to close Bootstrap modals
document.body.addEventListener('closeModal', () => {
  const modals = document.querySelectorAll('.modal.show');
  modals.forEach((modal) => {
    const bsModal = window.bootstrap?.Modal.getInstance(modal);
    if (bsModal) bsModal.hide();
  });
});

export { };
