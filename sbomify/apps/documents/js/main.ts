import 'vite/modulepreload-polyfill';
import '../../core/js/layout-interactions';
import { registerDocumentsTable } from './documents-table';
import { registerReleaseList } from '../../core/js/components/release-list';
import { initializeAlpine } from '../../core/js/alpine-init';

registerDocumentsTable();
registerReleaseList();

initializeAlpine();


import mountVueComponent from '../../core/js/common_vue';
import DocumentUpload from './components/DocumentUpload.vue';

mountVueComponent('vc-document-upload', DocumentUpload);
