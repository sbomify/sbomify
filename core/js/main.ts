import 'vite/modulepreload-polyfill';

import mountVueComponent from './common_vue';
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

// Declare the global feather variable
declare global {
  interface Window {
    feather: {
      replace(): void;
    };
  }
}

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
