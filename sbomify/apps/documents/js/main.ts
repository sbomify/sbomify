import 'vite/modulepreload-polyfill';
import '../../core/js/layout-interactions';
import Alpine from 'alpinejs';
import { registerDocumentsTable } from './documents_table';
import { registerReleaseList } from './release_list';
import { registerCopyableValue } from '../../core/js/components/copyable-value';

document.addEventListener('alpine:init', () => {
    registerCopyableValue();
    registerDocumentsTable();
    registerReleaseList();
});

Alpine.start();


import mountVueComponent from '../../core/js/common_vue';
import DocumentUpload from './components/DocumentUpload.vue';

mountVueComponent('vc-document-upload', DocumentUpload);
