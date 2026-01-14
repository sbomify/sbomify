import { registerCiCdInfo } from './ci-cd-info'
import { registerSbomsTable } from './sboms-table'
import { registerSbomUpload } from './sbom-upload'
import { registerContactsEditor } from './contacts-editor'
import { registerSupplierEditor } from './supplier-editor'
import { registerLicensesEditor } from './licenses-editor'
import { registerReleaseList } from '../../core/js/components/release-list'
import { registerAssessmentBadge } from '../../plugins/js/assessment-badge'
import { registerSiteNotifications } from '../../core/js/components/site-notifications'
import { initializeAlpine } from '../../core/js/alpine-init'

registerSbomsTable()
registerSbomUpload()
registerCiCdInfo()
registerContactsEditor()
registerSupplierEditor()
registerLicensesEditor()
registerReleaseList()
registerAssessmentBadge()
registerSiteNotifications()

void initializeAlpine()
