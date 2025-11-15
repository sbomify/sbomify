import 'vite/modulepreload-polyfill';
import './layout-interactions';

// Chart.js - make available globally for admin dashboard
import {
  Chart,
  CategoryScale,
  LinearScale,
  BarElement,
  Title,
  Tooltip,
  Legend,
} from 'chart.js';

// Register Chart.js components
Chart.register(
  CategoryScale,
  LinearScale,
  BarElement,
  Title,
  Tooltip,
  Legend
);

// Make Chart available globally
declare global {
  interface Window {
    Chart: typeof Chart;
  }
}

window.Chart = Chart;
// Import Vue component mounting utility
import mountVueComponent from './common_vue';
import './alerts-global'; // Ensure alerts are available globally
import { eventBus, EVENTS } from './utils';
import EditableSingleField from './components/EditableSingleField.vue';
import CopyableValue from './components/CopyableValue.vue';
import ConfirmAction from './components/ConfirmAction.vue';
import CopyToken from './components/CopyToken.vue';
import SiteNotifications from './components/SiteNotifications.vue';
import StandardCard from './components/StandardCard.vue';
import PlanCard from './components/PlanCard.vue';
import AccessTokensList from './components/AccessTokensList.vue';
import PublicStatusToggle from './components/PublicStatusToggle.vue';
import ComponentMetaInfo from './components/ComponentMetaInfo.vue';
import ComponentMetaInfoEditor from './components/ComponentMetaInfoEditor.vue';
import ComponentMetaInfoDisplay from './components/ComponentMetaInfoDisplay.vue';
import DangerZone from './components/DangerZone.vue';
import ProjectDangerZone from './components/ProjectDangerZone.vue';
import ProductDangerZone from './components/ProductDangerZone.vue';
import ExportDataCard from './components/ExportDataCard.vue';
import ItemAssignmentManager from './components/ItemAssignmentManager.vue';
import ItemsListTable from './components/ItemsListTable.vue';
import PublicCard from './components/PublicCard.vue';
import PublicPageLayout from './components/PublicPageLayout.vue';
import PublicProjectComponents from './components/PublicProjectComponents.vue';
import PublicProductProjects from './components/PublicProductProjects.vue';
import PublicDownloadCard from './components/PublicDownloadCard.vue';
import ProductIdentifiers from './components/ProductIdentifiers.vue';
import ProductLinks from './components/ProductLinks.vue';
import ProductReleases from './components/ProductReleases.vue';
import ReleaseArtifacts from './components/ReleaseArtifacts.vue';
import ReleaseDangerZone from './components/ReleaseDangerZone.vue';
import PublicReleaseArtifacts from './components/PublicReleaseArtifacts.vue';

import ReleaseList from './components/ReleaseList.vue';

// Initialize Vue components
mountVueComponent('vc-editable-single-field', EditableSingleField);
mountVueComponent('vc-copyable-value', CopyableValue);
mountVueComponent('vc-confirm-action', ConfirmAction);
mountVueComponent('vc-copy-token', CopyToken);
mountVueComponent('vc-site-notifications', SiteNotifications);
mountVueComponent('vc-standard-card', StandardCard);
mountVueComponent('vc-plan-card', PlanCard);
mountVueComponent('vc-access-tokens-list', AccessTokensList);
mountVueComponent('vc-public-status-toggle', PublicStatusToggle);
mountVueComponent('vc-component-meta-info', ComponentMetaInfo);
mountVueComponent('vc-component-meta-info-editor', ComponentMetaInfoEditor);
mountVueComponent('vc-component-meta-info-display', ComponentMetaInfoDisplay);
mountVueComponent('vc-danger-zone', DangerZone);
mountVueComponent('vc-project-danger-zone', ProjectDangerZone);
mountVueComponent('vc-product-danger-zone', ProductDangerZone);
mountVueComponent('vc-export-data-card', ExportDataCard);
mountVueComponent('vc-item-assignment-manager', ItemAssignmentManager);
mountVueComponent('vc-items-list-table', ItemsListTable);
mountVueComponent('vc-public-card', PublicCard);
mountVueComponent('vc-public-page-layout', PublicPageLayout);
mountVueComponent('vc-public-project-components', PublicProjectComponents);
mountVueComponent('vc-public-product-projects', PublicProductProjects);
mountVueComponent('vc-public-download-card', PublicDownloadCard);
mountVueComponent('vc-product-identifiers', ProductIdentifiers);
mountVueComponent('vc-product-links', ProductLinks);
mountVueComponent('vc-product-releases', ProductReleases);
mountVueComponent('vc-release-artifacts', ReleaseArtifacts);
mountVueComponent('vc-release-danger-zone', ReleaseDangerZone);
mountVueComponent('vc-public-release-artifacts', PublicReleaseArtifacts);

mountVueComponent('vc-release-list', ReleaseList);

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
export {};
