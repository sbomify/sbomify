import 'vite/modulepreload-polyfill';

import mountVueComponent from '../../core/js/common_vue';
import TeamBranding from './components/TeamBranding.vue';
import TeamDangerZone from './components/TeamDangerZone.vue';

mountVueComponent('vc-team-branding', TeamBranding);
mountVueComponent('vc-team-danger-zone', TeamDangerZone);
