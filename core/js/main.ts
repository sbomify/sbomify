import 'vite/modulepreload-polyfill';

// Type declaration for bootstrap module (avoids needing @types/bootstrap in production)
declare module 'bootstrap';

// Bootstrap JS - make available globally for Vue components
import * as bootstrap from 'bootstrap';

// Extend the Window interface to include bootstrap
declare global {
  interface Window {
    bootstrap: typeof bootstrap;
  }
}

window.bootstrap = bootstrap;

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

// FontAwesome CSS - loaded via Django templates, not needed here

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

  // Initialize sidebar toggle functionality
  const sidebarToggle = document.querySelector('.js-sidebar-toggle') as HTMLElement;
  const sidebar = document.querySelector('.sidebar') as HTMLElement;
  const body = document.body;

  if (sidebarToggle && sidebar) {
    sidebarToggle.addEventListener('click', (e) => {
      e.preventDefault();

      // For mobile: toggle visibility
      if (window.innerWidth < 992) {
        body.classList.toggle('sidebar-show');
      } else {
        // For desktop: toggle collapsed state
        body.classList.toggle('sidebar-collapsed');
      }
    });

    // Close sidebar on mobile when clicking outside
    document.addEventListener('click', (e) => {
      if (window.innerWidth < 992 && body.classList.contains('sidebar-show')) {
        const target = e.target as HTMLElement;
        if (!sidebar.contains(target) && !sidebarToggle.contains(target)) {
          body.classList.remove('sidebar-show');
        }
      }
    });

    // Handle resize events
    window.addEventListener('resize', () => {
      if (window.innerWidth >= 992) {
        body.classList.remove('sidebar-show');
      }
    });
  }

  // FontAwesome icons are loaded via CSS, no initialization needed
});

// Export something to make TypeScript happy
export {};
