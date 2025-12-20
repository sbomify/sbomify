import 'vite/modulepreload-polyfill'
import '../../core/js/layout-interactions'
import { registerSbomsTable } from './sboms-table'
import { registerReleaseList } from '../../core/js/components/release-list'
import { registerNtiaComplianceBadge } from '../../core/js/components/ntia-compliance-badge'
import { initializeAlpine } from '../../core/js/alpine-init'

registerSbomsTable()
registerReleaseList()
registerNtiaComplianceBadge()

initializeAlpine()

import mountVueComponent from '../../core/js/common_vue'
import EditableSingleField from '../../core/js/components/EditableSingleField.vue'
import LicensesEditor from './components/LicensesEditor.vue'
import CiCdInfo from './components/CiCdInfo.vue'
import SbomUpload from './components/SbomUpload.vue'

mountVueComponent('vc-editable-single-field', EditableSingleField)
mountVueComponent('vc-licenses-editor', LicensesEditor)
mountVueComponent('vc-ci-cd-info', CiCdInfo)
mountVueComponent('vc-sbom-upload', SbomUpload)
