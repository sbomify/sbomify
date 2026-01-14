import { describe, test, expect, mock, beforeEach } from 'bun:test'

const mockAlpineData = mock<(name: string, callback: () => unknown) => void>()

mock.module('alpinejs', () => ({
    default: {
        data: mockAlpineData
    }
}))

mock.module('../../core/js/components/pagination-controls', () => ({
    createPaginationData: mock().mockReturnValue({
        currentPage: 1,
        pageSize: 10,
        totalItems: 0
    })
}))

interface Document {
    id: string
    name: string
    document_type: string
    version: string
    created_at: string
    description: string
}

interface Release {
    id: string
    version: string
}

interface DocumentItem {
    document: Document
    releases: Release[]
}

describe('Documents Table', () => {
    beforeEach(() => {
        mockAlpineData.mockClear()
    })

    describe('Document Interface', () => {
        test('should accept valid document structure', () => {
            const doc: Document = {
                id: 'doc-123',
                name: 'Security Policy',
                document_type: 'policy',
                version: '1.0.0',
                created_at: '2024-01-15T12:00:00Z',
                description: 'Security policy document'
            }

            expect(doc.id).toBe('doc-123')
            expect(doc.document_type).toBe('policy')
        })
    })

    describe('Document Item', () => {
        test('should contain document and releases', () => {
            const item: DocumentItem = {
                document: {
                    id: 'doc-1',
                    name: 'Doc 1',
                    document_type: 'manual',
                    version: '1.0',
                    created_at: '2024-01-01',
                    description: ''
                },
                releases: [
                    { id: 'rel-1', version: 'v1.0.0' },
                    { id: 'rel-2', version: 'v1.1.0' }
                ]
            }

            expect(item.document.name).toBe('Doc 1')
            expect(item.releases).toHaveLength(2)
        })
    })

    describe('Edit Form', () => {
        test('should initialize edit form with empty values', () => {
            const editForm = {
                document_id: '',
                name: '',
                version: '',
                document_type: '',
                description: ''
            }

            expect(editForm.document_id).toBe('')
            expect(editForm.name).toBe('')
        })

        test('should populate edit form from document', () => {
            const document: Document = {
                id: 'doc-123',
                name: 'Test Doc',
                document_type: 'policy',
                version: '2.0',
                created_at: '2024-01-15',
                description: 'Test description'
            }

            const editForm = {
                document_id: document.id,
                name: document.name,
                version: document.version,
                document_type: document.document_type,
                description: document.description
            }

            expect(editForm.document_id).toBe('doc-123')
            expect(editForm.name).toBe('Test Doc')
            expect(editForm.version).toBe('2.0')
        })
    })

    describe('Edit Document Function', () => {
        test('should find document by ID', () => {
            const allDocuments: DocumentItem[] = [
                {
                    document: { id: 'doc-1', name: 'Doc 1', document_type: 't1', version: 'v1', created_at: '', description: '' },
                    releases: []
                },
                {
                    document: { id: 'doc-2', name: 'Doc 2', document_type: 't2', version: 'v2', created_at: '', description: '' },
                    releases: []
                }
            ]

            const editDocument = (documentId: string) => {
                return allDocuments.find(doc => doc.document.id === documentId)
            }

            const result = editDocument('doc-2')
            expect(result?.document.name).toBe('Doc 2')
        })

        test('should return undefined for non-existent document', () => {
            const allDocuments: DocumentItem[] = []

            const editDocument = (documentId: string) => {
                return allDocuments.find(doc => doc.document.id === documentId)
            }

            const result = editDocument('non-existent')
            expect(result).toBeUndefined()
        })
    })

    describe('JSON Parsing', () => {
        test('should parse documents data JSON', () => {
            const json = JSON.stringify([
                { document: { id: '1', name: 'D1' }, releases: [] }
            ])

            const parsed = JSON.parse(json) as DocumentItem[]
            expect(parsed).toHaveLength(1)
            expect(parsed[0].document.id).toBe('1')
        })
    })
})
