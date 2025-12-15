import 'vite/modulepreload-polyfill';
import '../../core/js/layout-interactions';
import Alpine from 'alpinejs';
import { registerDocumentsTable } from './documents-table';
import { registerReleaseList } from '../../core/js/components/release-list';

document.addEventListener('alpine:init', () => {
    registerDocumentsTable();
    registerReleaseList();
});

Alpine.start();


import mountVueComponent from '../../core/js/common_vue';
import DocumentUpload from './components/DocumentUpload.vue';

mountVueComponent('vc-document-upload', DocumentUpload);
