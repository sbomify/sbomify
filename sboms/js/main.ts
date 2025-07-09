import 'vite/modulepreload-polyfill'

import mountVueComponent from '../../core/js/common_vue'
import EditableSingleField from '../../core/js/components/EditableSingleField.vue'
import LicensesEditor from './components/LicensesEditor.vue'
import CiCdInfo from './components/CiCdInfo.vue'
import SbomUpload from './components/SbomUpload.vue'
import DashboardStats from './components/DashboardStats.vue'
import SbomsTable from './components/SbomsTable.vue'
import SbomMetadataCard from './components/SbomMetadataCard.vue'

import SbomActionsCard from './components/SbomActionsCard.vue'
import NTIAComplianceBadge from './components/NTIAComplianceBadge.vue'

mountVueComponent('vc-editable-single-field', EditableSingleField)
mountVueComponent('vc-licenses-editor', LicensesEditor)
mountVueComponent('vc-ci-cd-info', CiCdInfo)
mountVueComponent('vc-sbom-upload', SbomUpload)
mountVueComponent('vc-dashboard-stats', DashboardStats)
mountVueComponent('vc-sboms-table', SbomsTable)
mountVueComponent('vc-sbom-metadata-card', SbomMetadataCard)

mountVueComponent('vc-sbom-actions-card', SbomActionsCard)
mountVueComponent('vc-ntia-compliance-badge', NTIAComplianceBadge)
