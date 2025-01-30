import 'vite/modulepreload-polyfill';

import mountVueComponent from '../../core/js/common_vue';
import TeamBranding from './components/TeamBranding.vue';

mountVueComponent('vc-team-branding', TeamBranding);
