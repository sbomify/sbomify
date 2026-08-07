import { registerSbomsTable } from './sboms-table'
import { registerSbomUpload } from './sbom-upload'
import { registerContactsEditor } from './contacts-editor'
import { registerSupplierEditor } from './supplier-editor'
import { registerLicensesEditor } from './licenses-editor'
import { registerReleaseList } from '../../core/js/components/release-list'
import { registerAssessmentBadge } from '../../plugins/js/assessment-badge'
import { initializeAlpine } from '../../core/js/alpine-init'
import { registerCiCdToken } from './ci-cd-token'

registerSbomsTable()
registerSbomUpload()
registerContactsEditor()
registerSupplierEditor()
registerLicensesEditor()
registerReleaseList()
registerAssessmentBadge()
registerCiCdToken()

void initializeAlpine()
