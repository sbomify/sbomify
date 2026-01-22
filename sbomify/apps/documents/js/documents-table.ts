import Alpine from 'alpinejs'
import { createPaginationData } from '../../core/js/components/pagination-controls'

interface Document {
  id: string
  name: string
  document_type: string
  compliance_subcategory?: string
  version: string
  created_at: string
  description: string
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
  Alpine.data('documentsTable', (componentId: string, documentsDataJson: string) => {
    const allDocuments: DocumentItem[] = JSON.parse(documentsDataJson)

    return {
      componentId,
      allDocuments,
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

      ...createPaginationData(allDocuments.length, [10, 15, 25, 50, 100], 1),

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
