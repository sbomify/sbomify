import { registerCiCdInfo } from './ci-cd-info'
import { registerSbomsTable } from './sboms-table'
import { registerSbomUpload } from './sbom-upload'
import { registerContactsEditor } from './contacts-editor'
import { registerSupplierEditor } from './supplier-editor'
import { registerLicensesEditor } from './licenses-editor'
import { registerReleaseList } from '../../core/js/components/release-list'
import { registerNtiaComplianceBadge } from '../../core/js/components/ntia-compliance-badge'
import { initializeAlpine } from '../../core/js/alpine-init'
registerSbomsTable()
registerSbomUpload()
registerCiCdInfo()
registerContactsEditor()
registerSupplierEditor()
registerLicensesEditor()
registerReleaseList()
registerNtiaComplianceBadge()

void initializeAlpine()
