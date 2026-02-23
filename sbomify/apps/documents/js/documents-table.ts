import Alpine from 'alpinejs'
import { parseJsonScript } from '../../core/js/utils'

interface Document {
  id: string
  name: string
  document_type: string
  document_type_display?: string
  compliance_subcategory?: string
  version: string
  created_at: string
  description: string
}

interface Release {
  id: string
  name?: string
  version: string
  [key: string]: unknown
}

interface DocumentItem {
  document: Document
  releases: Release[]
}

type SortColumn = 'name' | 'document_type' | 'version' | 'created_at'
type SortDirection = 'asc' | 'desc'

export function registerDocumentsTable() {
  Alpine.data('documentsTable', (componentId: string) => {
    let afterSettleHandler: (() => void) | null = null
    let containerRef: HTMLElement | null = null

    return {
      componentId,
      allDocuments: parseJsonScript<DocumentItem[]>('documents-data') || [],
      search: '',
      sortColumn: 'created_at' as SortColumn,
      sortDirection: 'desc' as SortDirection,
      currentPage: 1,
      pageSize: 10,
      pageSizeOptions: [10, 15, 25, 50, 100],

      init(): void {
        const alpineThis = this as typeof this & { $el: HTMLElement }
        containerRef = alpineThis.$el.closest<HTMLElement>('#documents-table-container')
        if (!containerRef) return
        afterSettleHandler = () => {
          this.allDocuments = parseJsonScript<DocumentItem[]>('documents-data') || []
          if (this.currentPage > this.totalPages && this.totalPages > 0) {
            this.currentPage = this.totalPages
          }
        }
        containerRef.addEventListener('htmx:afterSettle', afterSettleHandler)
      },

      destroy(): void {
        if (afterSettleHandler && containerRef) {
          containerRef.removeEventListener('htmx:afterSettle', afterSettleHandler)
          afterSettleHandler = null
          containerRef = null
        }
      },

      editForm: {
        document_id: '',
        name: '',
        version: '',
        document_type: '',
        compliance_subcategory: '',
        description: ''
      } as {
        document_id: string
        name: string
        version: string
        document_type: string
        compliance_subcategory: string
        [key: string]: string
      },

      get filteredData(): DocumentItem[] {
        let data = [...this.allDocuments]
        if (this.search) {
          const s = this.search.toLowerCase()
          data = data.filter(
            item =>
              item.document.name.toLowerCase().includes(s) ||
              item.document.version.toLowerCase().includes(s) ||
              (item.document.document_type_display || item.document.document_type).toLowerCase().includes(s)
          )
        }
        return data
      },

      get sortedData(): DocumentItem[] {
        return [...this.filteredData].sort((a, b) => {
          let aVal: string | number
          let bVal: string | number

          switch (this.sortColumn) {
            case 'name':
              aVal = a.document.name.toLowerCase()
              bVal = b.document.name.toLowerCase()
              break
            case 'document_type':
              aVal = (a.document.document_type_display || a.document.document_type).toLowerCase()
              bVal = (b.document.document_type_display || b.document.document_type).toLowerCase()
              break
            case 'version':
              aVal = a.document.version.toLowerCase()
              bVal = b.document.version.toLowerCase()
              break
            case 'created_at':
              aVal = new Date(a.document.created_at).getTime()
              bVal = new Date(b.document.created_at).getTime()
              break
            default:
              return 0
          }

          if (aVal < bVal) return this.sortDirection === 'asc' ? -1 : 1
          if (aVal > bVal) return this.sortDirection === 'asc' ? 1 : -1
          return 0
        })
      },

      get paginatedData(): DocumentItem[] {
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
        const start = (this.currentPage - 1) * this.pageSize
        const end = start + this.pageSize
        return index >= start && index < end
      },

      editDocument(documentId: string): void {
        const item = this.allDocuments.find(doc => doc.document.id === documentId)
        if (!item) return

        this.editForm = {
          document_id: item.document.id,
          name: item.document.name,
          version: item.document.version,
          document_type: item.document.document_type,
          compliance_subcategory: item.document.compliance_subcategory || '',
          description: item.document.description
        }
      }
    }
  })
}
