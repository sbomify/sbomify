import Alpine from '../../core/js/alpine-init'
import { createPaginationData } from '../../core/js/components/pagination-controls'

interface Sbom {
  id: string
  name: string
  format: string
  format_version: string
  version: string
  created_at: string
  ntia_compliance_status?: string
  ntia_compliance_details?: {
    errors?: Array<{
      field: string
      message: string
      suggestion: string
    }>
    checked_at?: string
    error_count?: number
  }
}

interface Release {
  id: string
  name: string
  product_id: string
  product_name: string
  is_latest: boolean
  is_prerelease: boolean
  is_public: boolean
}

interface SbomItem {
  sbom: Sbom
  has_vulnerabilities_report: boolean
  releases: Release[]
}

export function registerSbomsTable() {
  Alpine.data('sbomsTable', (componentId: string, sbomsDataJson: string) => {
    const allSboms: SbomItem[] = JSON.parse(sbomsDataJson)

    return {
      componentId,
      allSboms,
      ...createPaginationData(allSboms.length, [10, 15, 25, 50, 100], 1)
    }
  })
}
