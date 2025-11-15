import 'vite/modulepreload-polyfill';
import { createApp, type Component } from 'vue';

// Vue components (using standard Bootstrap/HTML classes provided by our CSS system)
import ContactProfiles from './components/ContactProfiles.vue';
import TeamBranding from './components/TeamBranding.vue';
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

    // Create Vue app (using our modular CSS system)
    const app = createApp(component, elementProps);
    app.mount(element);
  });
}

// Mount components when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
  mountVueComponent('vc-contact-profiles', ContactProfiles);
  mountVueComponent('vc-team-branding', TeamBranding);
  mountVueComponent('vc-vulnerability-settings', VulnerabilitySettings);
});
