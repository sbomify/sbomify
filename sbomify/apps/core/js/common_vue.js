import { createApp } from 'vue'

// Note: Vuetify removed as components use standard Bootstrap/HTML classes
// which are now provided by our modular CSS system

function mountVueComponent(elementClass, Component) {
  console.log('Mounting Vue component', elementClass);
  const elements = document.getElementsByClassName(elementClass);
  if (elements.length > 0) {
    for (let i = 0; i < elements.length; i++) {
      try {
        // Check if element already has a Vue instance mounted
        if (elements[i].__vue_app__) {
          continue; // Skip if already mounted
        }

        // Convert dataset to props with proper formatting
        const dataProps = {};
        for (const [key, value] of Object.entries(elements[i].dataset)) {
          // Convert kebab-case to camelCase
          const camelKey = key.replace(/-([a-z])/g, (g) => g[1].toUpperCase());

          // Try to parse JSON values, otherwise use string
          try {
            if (value === 'true') dataProps[camelKey] = true;
            else if (value === 'false') dataProps[camelKey] = false;
            else if (value && !isNaN(value)) dataProps[camelKey] = Number(value);
            else if (value && (value.startsWith('{') || value.startsWith('['))) {
              dataProps[camelKey] = JSON.parse(value);
            } else {
              dataProps[camelKey] = value;
            }
          } catch {
            dataProps[camelKey] = value;
          }
        }

        const app = createApp(Component, dataProps);
        app.mount(elements[i]);
        console.log('Mounted Vue component', elementClass, 'with props:', dataProps);
      } catch (error) {
        console.error('Error mounting Vue component', elementClass, ':', error);
      }
    }
    return;
  }
}

export default mountVueComponent;
