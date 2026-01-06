import Alpine from '../../core/js/alpine-init'
import { createPaginationData } from '../../core/js/components/pagination-controls'

interface Sbom {
  id: string
  name: string
  format: string
  format_version: string
  version: string
  created_at: string
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

interface PluginResult {
  name: string
  display_name: string
  status: 'pass' | 'fail' | 'pending' | 'error'
  findings_count: number
  fail_count: number
}

interface AssessmentsData {
  sbom_id: string
  overall_status: 'all_pass' | 'has_failures' | 'pending' | 'in_progress' | 'no_assessments'
  total_assessments: number
  passing_count: number
  failing_count: number
  pending_count: number
  plugins: PluginResult[]
}

interface SbomItem {
  sbom: Sbom
  has_vulnerabilities_report: boolean
  releases: Release[]
  assessments?: AssessmentsData
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
