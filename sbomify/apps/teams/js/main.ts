import 'vite/modulepreload-polyfill';
import '../../core/js/layout-interactions';
import { createApp, type Component } from 'vue';

// Vue components (using standard Bootstrap/HTML classes provided by our CSS system)
import ContactProfiles from './components/ContactProfiles.vue';
import TeamBilling from './components/TeamBilling.vue';
import TeamBranding from './components/TeamBranding.vue';
import TeamDangerZone from './components/TeamDangerZone.vue';
import TeamInvitations from './components/TeamInvitations.vue';
import TeamMembers from './components/TeamMembers.vue';
import VulnerabilitySettings from './components/VulnerabilitySettings.vue';

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

    // Create Vue app (using our modular CSS system)
    const app = createApp(component, elementProps);
    app.mount(element);
  });
}

// Mount components when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
  mountVueComponent('vc-contact-profiles', ContactProfiles);
  mountVueComponent('vc-team-branding', TeamBranding);
  mountVueComponent('vc-team-billing', TeamBilling);
  mountVueComponent('vc-team-danger-zone', TeamDangerZone);
  mountVueComponent('vc-team-invitations', TeamInvitations);
  mountVueComponent('vc-team-members', TeamMembers);
  mountVueComponent('vc-vulnerability-settings', VulnerabilitySettings);
});
