import Alpine from '../../core/js/alpine-init'

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
  category?: 'attestation' | 'security' | 'license' | 'compliance'
  findings_count: number
  fail_count: number
}

interface AssessmentsData {
  sbom_id: string
  overall_status:
    | 'all_pass'
    | 'has_failures'
    | 'pending'
    | 'in_progress'
    | 'no_assessments'
    | 'no_plugins_enabled'
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
  assessments?: AssessmentsData | null
}

type SortColumn = 'name' | 'format' | 'version' | 'created_at'
type SortDirection = 'asc' | 'desc'

export function registerSbomsTable() {
  Alpine.data('sbomsTable', (componentId: string, sbomsDataJson: string) => {
    const allSboms: SbomItem[] = JSON.parse(sbomsDataJson)

    let afterSettleHandler: (() => void) | null = null

    return {
      componentId,
      allSboms,
      search: '',
      sortColumn: 'created_at' as SortColumn,
      sortDirection: 'desc' as SortDirection,
      currentPage: 1,
      pageSize: 10,
      pageSizeOptions: [10, 15, 25, 50, 100],

      init(): void {
        const container = document.getElementById('sboms-table-container')
        if (!container) return
        afterSettleHandler = () => {
          const el = document.getElementById('sboms-data')
          if (el?.textContent) {
            this.allSboms = JSON.parse(el.textContent)
            if (this.currentPage > this.totalPages && this.totalPages > 0) {
              this.currentPage = this.totalPages
            }
          }
        }
        container.addEventListener('htmx:afterSettle', afterSettleHandler)
      },

      destroy(): void {
        if (afterSettleHandler) {
          const container = document.getElementById('sboms-table-container')
          container?.removeEventListener('htmx:afterSettle', afterSettleHandler)
          afterSettleHandler = null
        }
      },

      get filteredData(): SbomItem[] {
        let data = [...this.allSboms]
        if (this.search) {
          const s = this.search.toLowerCase()
          data = data.filter(
            item =>
              item.sbom.name.toLowerCase().includes(s) ||
              item.sbom.version.toLowerCase().includes(s) ||
              item.sbom.format.toLowerCase().includes(s)
          )
        }
        return data
      },

      get sortedData(): SbomItem[] {
        return [...this.filteredData].sort((a, b) => {
          let aVal: string | number
          let bVal: string | number

          switch (this.sortColumn) {
            case 'name':
              aVal = a.sbom.name.toLowerCase()
              bVal = b.sbom.name.toLowerCase()
              break
            case 'format':
              aVal = a.sbom.format.toLowerCase()
              bVal = b.sbom.format.toLowerCase()
              break
            case 'version':
              aVal = a.sbom.version.toLowerCase()
              bVal = b.sbom.version.toLowerCase()
              break
            case 'created_at':
              aVal = new Date(a.sbom.created_at).getTime()
              bVal = new Date(b.sbom.created_at).getTime()
              break
            default:
              return 0
          }

          if (aVal < bVal) return this.sortDirection === 'asc' ? -1 : 1
          if (aVal > bVal) return this.sortDirection === 'asc' ? 1 : -1
          return 0
        })
      },

      get paginatedData(): SbomItem[] {
        const start = (this.currentPage - 1) * this.pageSize
        return this.sortedData.slice(start, start + this.pageSize)
      },

      get totalPages(): number {
        return Math.ceil(this.filteredData.length / this.pageSize) || 1
      },

      get startItem(): number {
        return this.filteredData.length === 0 ? 0 : (this.currentPage - 1) * this.pageSize + 1
      },

      get endItem(): number {
        return Math.min(this.currentPage * this.pageSize, this.filteredData.length)
      },

      get visiblePages(): (number | string)[] {
        const pages: (number | string)[] = []
        const total = this.totalPages
        const current = this.currentPage

        if (total <= 7) {
          for (let i = 1; i <= total; i++) pages.push(i)
        } else {
          pages.push(1)
          if (current > 3) pages.push('...')
          for (let i = Math.max(2, current - 1); i <= Math.min(total - 1, current + 1); i++) {
            pages.push(i)
          }
          if (current < total - 2) pages.push('...')
          pages.push(total)
        }
        return pages
      },

      sort(column: SortColumn): void {
        if (this.sortColumn === column) {
          this.sortDirection = this.sortDirection === 'asc' ? 'desc' : 'asc'
        } else {
          this.sortColumn = column
          this.sortDirection = 'asc'
        }
        this.currentPage = 1
      },

      goToPage(page: number): void {
        if (page >= 1 && page <= this.totalPages) {
          this.currentPage = page
        }
      },

      isVisible(index: number): boolean {
        // For sorted/filtered data, we use paginatedData directly
        // This is kept for backward compatibility
        const start = (this.currentPage - 1) * this.pageSize
        const end = start + this.pageSize
        return index >= start && index < end
      }
    }
  })
}
