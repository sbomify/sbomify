import 'vite/modulepreload-polyfill';

import mountVueComponent from '../../core/js/common_vue';
import PublicStatusToggle from './components/PublicStatusToggle.vue';
import ComponentMetaInfoEditor from './components/ComponentMetaInfoEditor.vue';
import ComponentMetaInfoDisplay from './components/ComponentMetaInfoDisplay.vue';
import ComponentMetaInfo from './components/ComponentMetaInfo.vue';
import CiCdInfo from './components/CiCdInfo.vue';
import DashboardStats from './components/DashboardStats.vue';

mountVueComponent('vc-public-status-toggle', PublicStatusToggle);
mountVueComponent('vc-component-meta-info-editor', ComponentMetaInfoEditor);
mountVueComponent('vc-component-meta-info-display', ComponentMetaInfoDisplay);
mountVueComponent('vc-component-meta-info', ComponentMetaInfo);
mountVueComponent('vc-ci-cd-info', CiCdInfo);
mountVueComponent('vc-dashboard-stats', DashboardStats);
