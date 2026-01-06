import 'vite/modulepreload-polyfill';
import './layout-interactions';
import './navbar-search';
import './notifications-modal';

// Shared Chart.js setup (makes window.Chart available)
import './chart-setup';
import * as bootstrap from 'bootstrap';
import Alpine from 'alpinejs';
// Import Vue component mounting utility
import mountVueComponent from './common_vue';
import './alerts-global'; // Ensure alerts are available globally
import './clipboard-global'; // Clipboard utilities with auto-initialization
import { eventBus, EVENTS } from './utils';

import { registerCopyableValue } from './components/copyable-value';
import { registerPublicStatusToggle } from './components/public-status-toggle';
import { registerWorkspaceSwitcher } from './components/workspace-switcher';
import { registerAccessTokensList } from './components/access-tokens-list';
import { registerDeleteModal } from './components/delete-modal';
import { registerReleaseList } from './components/release-list';
import { registerAssessmentBadge } from '../../plugins/js/assessment-badge';
import { registerComponentMetaInfoEditor } from './component-meta-info-editor';
import { registerComponentMetaInfo } from './component-meta-info';
import { initializeAlpine } from './alpine-init';

import { registerSbomUpload } from '../../sboms/js/sbom-upload';
import { registerCiCdInfo } from '../../sboms/js/ci-cd-info';
import { registerContactsEditor } from '../../sboms/js/contacts-editor';
import { registerSupplierEditor } from '../../sboms/js/supplier-editor';
import { registerLicensesEditor } from '../../sboms/js/licenses-editor';
import { registerDocumentUpload } from '../../documents/js/document-upload';
import { registerSbomsTable } from '../../sboms/js/sboms-table';

import '../../vulnerability_scanning/js/vulnerability-chart';

import EditableSingleField from './components/EditableSingleField.vue';
import ConfirmAction from './components/ConfirmAction.vue';
import CopyToken from './components/CopyToken.vue';
import SiteNotifications from './components/SiteNotifications.vue';
import StandardCard from './components/StandardCard.vue';
import PlanCard from './components/PlanCard.vue';
import ExportDataCard from './components/ExportDataCard.vue';
import ItemAssignmentManager from './components/ItemAssignmentManager.vue';
import ItemsListTable from './components/ItemsListTable.vue';
import PublicCard from './components/PublicCard.vue';
import PublicProductProjects from './components/PublicProductProjects.vue';
import PublicDownloadCard from './components/PublicDownloadCard.vue';
import ProductIdentifiers from './components/ProductIdentifiers.vue';
import ProductLinks from './components/ProductLinks.vue';
import ProductReleases from './components/ProductReleases.vue';
import ReleaseArtifacts from './components/ReleaseArtifacts.vue';
import PublicReleaseArtifacts from './components/PublicReleaseArtifacts.vue';

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
registerAssessmentBadge();
registerDocumentUpload();
registerDeleteModal();
registerSbomsTable();
registerComponentMetaInfoEditor();
registerComponentMetaInfo();

// Initialize Alpine
void initializeAlpine();

// Initialize Vue components
mountVueComponent('vc-editable-single-field', EditableSingleField);
mountVueComponent('vc-confirm-action', ConfirmAction);
mountVueComponent('vc-copy-token', CopyToken);
mountVueComponent('vc-site-notifications', SiteNotifications);
mountVueComponent('vc-standard-card', StandardCard);
mountVueComponent('vc-plan-card', PlanCard);

mountVueComponent('vc-export-data-card', ExportDataCard);
mountVueComponent('vc-item-assignment-manager', ItemAssignmentManager);
mountVueComponent('vc-items-list-table', ItemsListTable);
mountVueComponent('vc-public-card', PublicCard);
mountVueComponent('vc-public-product-projects', PublicProductProjects);
mountVueComponent('vc-public-download-card', PublicDownloadCard);
mountVueComponent('vc-product-identifiers', ProductIdentifiers);
mountVueComponent('vc-product-links', ProductLinks);
mountVueComponent('vc-product-releases', ProductReleases);
mountVueComponent('vc-release-artifacts', ReleaseArtifacts);
mountVueComponent('vc-public-release-artifacts', PublicReleaseArtifacts);

// Re-mount Vue components after HTMX content swaps
document.body.addEventListener('htmx:afterSwap', () => {
  mountVueComponent('vc-editable-single-field', EditableSingleField);
  mountVueComponent('vc-confirm-action', ConfirmAction);
  mountVueComponent('vc-copy-token', CopyToken);
  mountVueComponent('vc-site-notifications', SiteNotifications);
  mountVueComponent('vc-standard-card', StandardCard);
  mountVueComponent('vc-plan-card', PlanCard);

  mountVueComponent('vc-export-data-card', ExportDataCard);
  mountVueComponent('vc-item-assignment-manager', ItemAssignmentManager);
  mountVueComponent('vc-items-list-table', ItemsListTable);
  mountVueComponent('vc-public-card', PublicCard);
  mountVueComponent('vc-public-product-projects', PublicProductProjects);
  mountVueComponent('vc-public-download-card', PublicDownloadCard);
  mountVueComponent('vc-product-identifiers', ProductIdentifiers);
  mountVueComponent('vc-product-links', ProductLinks);
  mountVueComponent('vc-product-releases', ProductReleases);
  mountVueComponent('vc-release-artifacts', ReleaseArtifacts);
  mountVueComponent('vc-public-release-artifacts', PublicReleaseArtifacts);
});

export { };
