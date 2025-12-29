import 'vite/modulepreload-polyfill';
import './layout-interactions';
import './navbar-search';
import './notifications-modal';

// Chart.js - make available globally for admin dashboard and vulnerability trends
import {
  Chart,
  CategoryScale,
  LinearScale,
  BarElement,
  LineElement,
  PointElement,
  ArcElement,
  LineController,
  BarController,
  DoughnutController,
  Filler,
  Title,
  Tooltip,
  Legend,
} from 'chart.js';
import * as bootstrap from 'bootstrap';
import Alpine from 'alpinejs';
import { registerCopyableValue } from './components/copyable-value';
import { registerPublicStatusToggle } from './components/public-status-toggle';
import { registerWorkspaceSwitcher } from './components/workspace-switcher';
import { registerSbomUpload } from '../../sboms/js/sbom-upload';
import { registerDeleteModal } from './components/delete-modal';
import '../../vulnerability_scanning/js/vulnerability-chart';

// Register Chart.js components
Chart.register(
  CategoryScale,
  LinearScale,
  BarElement,
  LineElement,
  PointElement,
  ArcElement,
  LineController,
  BarController,
  DoughnutController,
  Filler,
  Title,
  Tooltip,
  Legend
);

// Make Chart available globally
declare global {
  interface Window {
    Chart: typeof Chart;
    Alpine: typeof Alpine;
    bootstrap: typeof bootstrap;
  }
}

window.Chart = Chart;
window.bootstrap = bootstrap;
// Import Vue component mounting utility
import mountVueComponent from './common_vue';
import './alerts-global'; // Ensure alerts are available globally
import './clipboard-global'; // Clipboard utilities with auto-initialization
import { eventBus, EVENTS } from './utils';
import EditableSingleField from './components/EditableSingleField.vue';
import ConfirmAction from './components/ConfirmAction.vue';
import CopyToken from './components/CopyToken.vue';
import SiteNotifications from './components/SiteNotifications.vue';
import StandardCard from './components/StandardCard.vue';
import PlanCard from './components/PlanCard.vue';
import AccessTokensList from './components/AccessTokensList.vue';
import ComponentMetaInfo from './components/ComponentMetaInfo.vue';
import ComponentMetaInfoEditor from './components/ComponentMetaInfoEditor.vue';
import ComponentMetaInfoDisplay from './components/ComponentMetaInfoDisplay.vue';
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

registerCopyableValue();
registerPublicStatusToggle();
registerWorkspaceSwitcher();
registerSbomUpload();
registerDeleteModal();

import { initializeAlpine } from './alpine-init';
initializeAlpine();

// Initialize Vue components
mountVueComponent('vc-editable-single-field', EditableSingleField);
mountVueComponent('vc-confirm-action', ConfirmAction);
mountVueComponent('vc-copy-token', CopyToken);
mountVueComponent('vc-site-notifications', SiteNotifications);
mountVueComponent('vc-standard-card', StandardCard);
mountVueComponent('vc-plan-card', PlanCard);
mountVueComponent('vc-access-tokens-list', AccessTokensList);
mountVueComponent('vc-component-meta-info', ComponentMetaInfo);
mountVueComponent('vc-component-meta-info-editor', ComponentMetaInfoEditor);
mountVueComponent('vc-component-meta-info-display', ComponentMetaInfoDisplay);
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
  mountVueComponent('vc-access-tokens-list', AccessTokensList);
  mountVueComponent('vc-component-meta-info', ComponentMetaInfo);
  mountVueComponent('vc-component-meta-info-editor', ComponentMetaInfoEditor);
  mountVueComponent('vc-component-meta-info-display', ComponentMetaInfoDisplay);
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

// Declare global variables
declare global {
  interface Window {
    eventBus: typeof eventBus;
    EVENTS: typeof EVENTS;
  }
}

// Make eventBus available globally for inline scripts
window.eventBus = eventBus;
window.EVENTS = EVENTS;

// Export something to make TypeScript happy
export { };
