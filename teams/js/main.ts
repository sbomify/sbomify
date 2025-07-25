import 'vite/modulepreload-polyfill';
import { createApp, type Component } from 'vue';

// Vuetify setup (copied from common_vue.js)
import 'vuetify/styles'
import { createVuetify } from 'vuetify'
import * as components from 'vuetify/components'
import * as directives from 'vuetify/directives'
import { aliases, mdi } from 'vuetify/iconsets/mdi-svg'

import TeamBilling from './components/TeamBilling.vue';
import TeamBranding from './components/TeamBranding.vue';
import TeamDangerZone from './components/TeamDangerZone.vue';
import TeamInvitations from './components/TeamInvitations.vue';
import TeamMembers from './components/TeamMembers.vue';
import VulnerabilitySettings from './components/VulnerabilitySettings.vue';
import TeamsList from './components/TeamsList.vue';

// Create vuetify instance with icons
const vuetify = createVuetify({
  components,
  directives,
  theme: {
    defaultTheme: 'light',
    themes: {
      light: {
        colors: {
          primary: '#3B7DDD',
          secondary: '#6c757d',
          success: '#28a745',
          warning: '#ffc107',
          danger: '#dc3545'
        }
      }
    }
  },
  icons: {
    defaultSet: 'mdi',
    aliases,
    sets: { mdi }
  }
});

// Function to mount Vue components with teams-specific data handling
function mountVueComponent(selector: string, component: Component, props: Record<string, unknown> = {}) {
  const elements = document.querySelectorAll(`[class*="${selector}"]`);

  elements.forEach((element) => {
    // Extract data attributes as props
    const elementProps = { ...props };

    // Convert data attributes to camelCase props
    for (const attr of element.attributes) {
      if (attr.name.startsWith('data-')) {
        const propName = attr.name
          .replace('data-', '')
          .replace(/-([a-z])/g, (_, letter) => letter.toUpperCase());
        elementProps[propName] = attr.value;
      }
    }

    // Special handling for JSON data elements (teams-specific)
    if (elementProps.teamMembersElementId) {
      const membersElement = document.getElementById(elementProps.teamMembersElementId as string);
      if (membersElement && membersElement.textContent) {
        try {
          elementProps.members = JSON.parse(membersElement.textContent);
        } catch (error) {
          console.error('Error parsing team members data:', error);
          elementProps.members = [];
        }
      }
    }

    if (elementProps.teamInvitationsElementId) {
      const invitationsElement = document.getElementById(elementProps.teamInvitationsElementId as string);
      if (invitationsElement && invitationsElement.textContent) {
        try {
          elementProps.invitations = JSON.parse(invitationsElement.textContent);
        } catch (error) {
          console.error('Error parsing team invitations data:', error);
          elementProps.invitations = [];
        }
      }
    }

    if (elementProps.billingPlanLimits) {
      if (elementProps.billingPlanLimits === '' || elementProps.billingPlanLimits === 'null') {
        elementProps.billingPlanLimits = null;
      } else {
        try {
          elementProps.billingPlanLimits = JSON.parse(elementProps.billingPlanLimits as string);
        } catch (error) {
          console.error('Error parsing billing plan limits:', error);
          elementProps.billingPlanLimits = null;
        }
      }
    } else {
      elementProps.billingPlanLimits = null;
    }

    // Create Vue app with Vuetify
    const app = createApp(component, elementProps);
    app.use(vuetify);
    app.mount(element);
  });
}

// Mount components when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
  mountVueComponent('vc-team-branding', TeamBranding);
  mountVueComponent('vc-team-billing', TeamBilling);
  mountVueComponent('vc-team-danger-zone', TeamDangerZone);
  mountVueComponent('vc-team-invitations', TeamInvitations);
  mountVueComponent('vc-team-members', TeamMembers);
  mountVueComponent('vc-vulnerability-settings', VulnerabilitySettings);
  mountVueComponent('vc-teams-list', TeamsList);
});
