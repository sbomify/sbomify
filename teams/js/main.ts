import 'vite/modulepreload-polyfill';
import { createApp, type Component } from 'vue';

import TeamBranding from './components/TeamBranding.vue';
import TeamDangerZone from './components/TeamDangerZone.vue';
import TeamsList from './components/TeamsList.vue';

// Function to mount Vue components
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

    const app = createApp(component, elementProps);
    app.mount(element);
  });
}

// Mount components when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
  mountVueComponent('vc-team-branding', TeamBranding);
  mountVueComponent('vc-team-danger-zone', TeamDangerZone);
  mountVueComponent('vc-teams-list', TeamsList);
});
