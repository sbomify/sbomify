import 'vite/modulepreload-polyfill';

import mountVueComponent from './common_vue';
import './alerts-global'; // Ensure alerts are available globally
import { eventBus, EVENTS } from './utils';
import EditableSingleField from './components/EditableSingleField.vue';
import CopyableValue from './components/CopyableValue.vue';
import ConfirmAction from './components/ConfirmAction.vue';
import DashboardStats from '../../sboms/js/components/DashboardStats.vue';
import CopyToken from './components/CopyToken.vue';
import SiteNotifications from './components/SiteNotifications.vue';
import StandardCard from './components/StandardCard.vue';
import StatCard from './components/StatCard.vue';
import PlanCard from './components/PlanCard.vue';
import AccessTokensList from './components/AccessTokensList.vue';
import PublicStatusToggle from './components/PublicStatusToggle.vue';
import ComponentMetaInfo from './components/ComponentMetaInfo.vue';
import ComponentMetaInfoEditor from './components/ComponentMetaInfoEditor.vue';
import ComponentMetaInfoDisplay from './components/ComponentMetaInfoDisplay.vue';
import DangerZone from './components/DangerZone.vue';
import ProjectDangerZone from './components/ProjectDangerZone.vue';
import ProductDangerZone from './components/ProductDangerZone.vue';
import AddProductForm from './components/AddProductForm.vue';
import AddProjectForm from './components/AddProjectForm.vue';
import AddComponentForm from './components/AddComponentForm.vue';
import ExportDataCard from './components/ExportDataCard.vue';
import ItemAssignmentManager from './components/ItemAssignmentManager.vue';
import ItemsListTable from './components/ItemsListTable.vue';
import ProductsList from './components/ProductsList.vue';
import ProjectsList from './components/ProjectsList.vue';
import ComponentsList from './components/ComponentsList.vue';
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

import ReleasesList from './components/ReleasesList.vue';
import ReleaseList from './components/ReleaseList.vue';


// Initialize Vue components
mountVueComponent('vc-editable-single-field', EditableSingleField);
mountVueComponent('vc-copyable-value', CopyableValue);
mountVueComponent('vc-confirm-action', ConfirmAction);
mountVueComponent('vc-dashboard-stats', DashboardStats);
mountVueComponent('vc-copy-token', CopyToken);
mountVueComponent('vc-site-notifications', SiteNotifications);
mountVueComponent('vc-standard-card', StandardCard);
mountVueComponent('vc-stat-card', StatCard);
mountVueComponent('vc-plan-card', PlanCard);
mountVueComponent('vc-access-tokens-list', AccessTokensList);
mountVueComponent('vc-public-status-toggle', PublicStatusToggle);
mountVueComponent('vc-component-meta-info', ComponentMetaInfo);
mountVueComponent('vc-component-meta-info-editor', ComponentMetaInfoEditor);
mountVueComponent('vc-component-meta-info-display', ComponentMetaInfoDisplay);
mountVueComponent('vc-danger-zone', DangerZone);
mountVueComponent('vc-project-danger-zone', ProjectDangerZone);
mountVueComponent('vc-product-danger-zone', ProductDangerZone);
mountVueComponent('vc-add-product-form', AddProductForm);
mountVueComponent('vc-add-project-form', AddProjectForm);
mountVueComponent('vc-add-component-form', AddComponentForm);
mountVueComponent('vc-export-data-card', ExportDataCard);
mountVueComponent('vc-item-assignment-manager', ItemAssignmentManager);
mountVueComponent('vc-items-list-table', ItemsListTable);
mountVueComponent('vc-products-list', ProductsList);
mountVueComponent('vc-projects-list', ProjectsList);
mountVueComponent('vc-components-list', ComponentsList);
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

mountVueComponent('vc-releases-list', ReleasesList);
mountVueComponent('vc-release-list', ReleaseList);

// Declare the global feather variable
declare global {
  interface Window {
    feather: {
      replace(): void;
    };
    eventBus: typeof eventBus;
    EVENTS: typeof EVENTS;
  }
}

// Make eventBus available globally for inline scripts
window.eventBus = eventBus;
window.EVENTS = EVENTS;



// Handle modal UX improvements
document.addEventListener('DOMContentLoaded', function() {
  // Initialize modals with custom focus management
  document.querySelectorAll('.modal').forEach(modalElement => {
    const modal = modalElement as HTMLElement;

    modal.addEventListener('shown.bs.modal', () => {
      const input = modal.querySelector('input[type="text"]') as HTMLInputElement;
      if (input) {
        setTimeout(() => {
          input.focus();
          input.select();
        }, 50);
      }
    });
  });

  // Initialize Feather icons
  window.feather.replace();
});

// Export something to make TypeScript happy
export {};
