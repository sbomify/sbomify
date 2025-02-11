import { createApp } from 'vue'

// Vuetify
import 'vuetify/styles'
import { createVuetify } from 'vuetify'
import * as components from 'vuetify/components'
import * as directives from 'vuetify/directives'
import { aliases, mdi } from 'vuetify/iconsets/mdi-svg'  // Use SVG icons instead of font

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
  blueprints: {
    defaults: {
      VBtn: {
        color: 'primary',
        variant: 'flat'
      }
    }
  },
  directives: {
    defaults: {
      'global': { disableGlobalStyles: true }
    }
  },
  icons: {
    defaultSet: 'mdi',
    aliases,
    sets: { mdi }
  }
})

function mountVueComponent(elementClass, Component) {
  console.log('Mounting Vue component', elementClass);
  const elements = document.getElementsByClassName(elementClass);
  if (elements.length > 0) {
    for (let i = 0; i < elements.length; i++) {
      const app = createApp(Component, elements[i].dataset);
      // Check if element already has a Vue instance mounted
      if (elements[i].__vue_app__) {
        continue; // Skip if already mounted
      }
      app.use(vuetify);
      app.mount(elements[i]);
      console.log('Mounted Vue component', elementClass);
    }
    return;
  }
}

export default mountVueComponent;
