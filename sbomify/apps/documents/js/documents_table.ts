import Alpine from 'alpinejs'
import { createPaginationData } from '../../core/js/components/pagination_controls'

interface Document {
  id: string
  name: string
  document_type: string
  version: string
  created_at: string
  description?: string
}

interface Release {
  id: string
  version: string
  [key: string]: unknown
}

interface DocumentItem {
  document: Document
  releases: Release[]
}

export function registerDocumentsTable() {
  Alpine.data('documentsTable', (dataJson: string) => {
    const data = JSON.parse(dataJson) as { 
      documentsData?: DocumentItem[]
      componentId?: string
      isPublicView?: boolean
      hasCrudPermissions?: boolean 
    }
    const allDocuments = (data.documentsData || []) as DocumentItem[]

    return {
      allDocuments,
      hasData: allDocuments.length > 0,
      documentToEdit: null as Document | null,
      isUpdating: false,
      editForm: {
        document_id: '',
        name: '',
        version: '',
        document_type: '',
        description: ''
      },
      componentId: data.componentId || '',
      isPublicView: data.isPublicView || false,
      hasCrudPermissions: data.hasCrudPermissions || false,

      ...createPaginationData(allDocuments.length, [10, 15, 25, 50, 100], 1),

      isVisible(index: number): boolean {
        const start = (this.currentPage - 1) * this.pageSize
        const end = start + this.pageSize
        return index >= start && index < end
      },

      getDocumentTypeDisplay(documentType: string): string {
        if (!documentType) return 'Document'
        const typeDisplayMap: { [key: string]: string } = {
          'specification': 'Specification',
          'manual': 'Manual',
          'readme': 'README',
          'documentation': 'Documentation',
          'build-instructions': 'Build Instructions',
          'configuration': 'Configuration',
          'license': 'License',
          'compliance': 'Compliance',
          'evidence': 'Evidence',
          'changelog': 'Changelog',
          'release-notes': 'Release Notes',
          'security-advisory': 'Security Advisory',
          'vulnerability-report': 'Vulnerability Report',
          'threat-model': 'Threat Model',
          'risk-assessment': 'Risk Assessment',
          'pentest-report': 'Penetration Test Report',
          'static-analysis': 'Static Analysis Report',
          'dynamic-analysis': 'Dynamic Analysis Report',
          'quality-metrics': 'Quality Metrics',
          'maturity-report': 'Maturity Report',
          'report': 'Report',
          'other': 'Other'
        }
        return typeDisplayMap[documentType] || documentType
          .split('-')
          .map(word => word.charAt(0).toUpperCase() + word.slice(1))
          .join(' ')
      },

      truncateText(text: string, maxLength: number): string {
        if (!text) return ''
        if (text.length <= maxLength) return text
        return text.substring(0, maxLength) + '...'
      },

      formatDate(dateString: string): string {
        try {
          const date = new Date(dateString)
          return date.toLocaleDateString()
        } catch {
          return dateString
        }
      },

      editDocument(documentId: string): void {
        const item = this.allDocuments.find(doc => doc.document.id === documentId)
        if (!item) return

        this.documentToEdit = item.document
        this.editForm = {
          document_id: item.document.id,
          name: item.document.name,
          version: item.document.version,
          document_type: item.document.document_type,
          description: item.document.description || ''
        }

        // Open Bootstrap modal
        this.$nextTick(() => {
          const modalEl = document.getElementById('edit-document-modal')
          if (modalEl) {
            // Process HTMX attributes on dynamically added modal
            const htmx = (window as typeof import('htmx.org')).htmx
            if (htmx) {
              htmx.process(modalEl)
            }
            
            const modal = new window.bootstrap.Modal(modalEl)
            modal.show()
          }
        })
      },

      cancelEdit(): void {
        // Close Bootstrap modal - the cleanup will happen in hidden.bs.modal event
        const modalEl = document.getElementById('edit-document-modal')
        if (modalEl) {
          const modalInstance = window.bootstrap.Modal.getInstance(modalEl)
          if (modalInstance) {
            modalInstance.hide()
          }
        }
      },

      handleEditSuccess(): void {
        // Update the document in the list
        const index = this.allDocuments.findIndex(
          doc => doc.document.id === this.editForm.document_id
        )
        if (index !== -1) {
          this.allDocuments[index].document.name = this.editForm.name
          this.allDocuments[index].document.version = this.editForm.version
          this.allDocuments[index].document.document_type = this.editForm.document_type
          this.allDocuments[index].document.description = this.editForm.description
        }
        this.cancelEdit()
      }
    }
  })
}
