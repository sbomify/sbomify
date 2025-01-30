import { createApp } from 'vue'

// Vuetify
// import 'vuetify/styles'
import { createVuetify } from 'vuetify'
import * as components from 'vuetify/components'
import * as directives from 'vuetify/directives'

const vuetify = createVuetify({
  components,
  directives,
  theme: {
    defaultTheme: 'light',
  }
})


function mountVueComponent(elementClass, Component) {
  // const elem = document.getElementById(elementId)
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
