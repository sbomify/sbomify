import 'vite/modulepreload-polyfill'
import '../../core/js/layout-interactions'

import mountVueComponent from '../../core/js/common_vue'
import DocumentUpload from './components/DocumentUpload.vue'
import DocumentsTable from './components/DocumentsTable.vue'

mountVueComponent('vc-document-upload', DocumentUpload)
mountVueComponent('vc-documents-table', DocumentsTable)
