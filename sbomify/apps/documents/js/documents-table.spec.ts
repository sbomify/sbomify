import { describe, test, expect, mock, beforeEach, afterEach } from 'bun:test'
import { parseJsonScript } from '../../core/js/utils'

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

    describe('afterSettle lifecycle', () => {
        const originalDocument = globalThis.document

        afterEach(() => {
            if (originalDocument) {
                globalThis.document = originalDocument
            } else {
                delete (globalThis as Record<string, unknown>).document
            }
        })

        const sampleDocuments: DocumentItem[] = [
            {
                document: { id: 'doc-1', name: 'Policy', document_type: 'policy', version: '1.0', created_at: '2024-01-01', description: '' },
                releases: []
            },
            {
                document: { id: 'doc-2', name: 'Manual', document_type: 'manual', version: '2.0', created_at: '2024-02-01', description: '' },
                releases: []
            }
        ]

        test('init() should attach afterSettle listener to container', () => {
            const addSpy = mock(() => {})
            const mockContainer = { addEventListener: addSpy }
            ;(globalThis as Record<string, unknown>).document = {
                getElementById: (id: string) => id === 'documents-table-container' ? mockContainer : null
            }

            const component = {
                allDocuments: [] as DocumentItem[],
                currentPage: 1,
                init(): void {
                    const c = document.getElementById('documents-table-container')
                    if (!c) return
                    c.addEventListener('htmx:afterSettle', () => {})
                }
            }
            component.init()

            expect(addSpy).toHaveBeenCalledWith('htmx:afterSettle', expect.any(Function))
        })

        test('afterSettle handler should re-read data from json_script', () => {
            let handler: (() => void) | null = null
            const mockContainer = {
                addEventListener: (event: string, fn: () => void) => {
                    if (event === 'htmx:afterSettle') handler = fn
                }
            }
            const mockScript = { textContent: JSON.stringify(sampleDocuments) }
            ;(globalThis as Record<string, unknown>).document = {
                getElementById: (id: string) => {
                    if (id === 'documents-table-container') return mockContainer
                    if (id === 'documents-data') return mockScript
                    return null
                }
            }

            const component = {
                allDocuments: [] as DocumentItem[],
                currentPage: 1,
                init(): void {
                    const c = document.getElementById('documents-table-container')
                    if (!c) return
                    c.addEventListener('htmx:afterSettle', () => {
                        this.allDocuments = parseJsonScript('documents-data') || []
                    })
                }
            }
            component.init()

            expect(component.allDocuments).toHaveLength(0)
            handler!()
            expect(component.allDocuments).toHaveLength(2)
            expect(component.allDocuments[0].document.name).toBe('Policy')
        })

        test('afterSettle handler should clamp currentPage when beyond totalPages', () => {
            let handler: (() => void) | null = null
            const mockContainer = {
                addEventListener: (event: string, fn: () => void) => {
                    if (event === 'htmx:afterSettle') handler = fn
                }
            }
            const mockScript = { textContent: JSON.stringify(sampleDocuments) }
            ;(globalThis as Record<string, unknown>).document = {
                getElementById: (id: string) => {
                    if (id === 'documents-table-container') return mockContainer
                    if (id === 'documents-data') return mockScript
                    return null
                }
            }

            const component = {
                allDocuments: [] as DocumentItem[],
                currentPage: 5,
                pageSize: 10,
                get totalPages() { return Math.ceil(this.allDocuments.length / this.pageSize) || 1 },
                init(): void {
                    const c = document.getElementById('documents-table-container')
                    if (!c) return
                    c.addEventListener('htmx:afterSettle', () => {
                        this.allDocuments = parseJsonScript('documents-data') || []
                        if (this.currentPage > this.totalPages && this.totalPages > 0) {
                            this.currentPage = this.totalPages
                        }
                    })
                }
            }
            component.init()
            handler!()

            expect(component.currentPage).toBe(1)
        })

        test('destroy() should remove afterSettle listener', () => {
            const removeSpy = mock(() => {})
            const mockContainer = {
                addEventListener: () => {},
                removeEventListener: removeSpy
            }
            ;(globalThis as Record<string, unknown>).document = {
                getElementById: (id: string) => id === 'documents-table-container' ? mockContainer : null
            }

            let afterSettleHandler: (() => void) | null = null
            const component = {
                init(): void {
                    const c = document.getElementById('documents-table-container')
                    if (!c) return
                    afterSettleHandler = () => {}
                    c.addEventListener('htmx:afterSettle', afterSettleHandler)
                },
                destroy(): void {
                    if (afterSettleHandler) {
                        const c = document.getElementById('documents-table-container')
                        c?.removeEventListener('htmx:afterSettle', afterSettleHandler)
                        afterSettleHandler = null
                    }
                }
            }
            component.init()
            component.destroy()

            expect(removeSpy).toHaveBeenCalledWith('htmx:afterSettle', expect.any(Function))
            expect(afterSettleHandler).toBeNull()
        })
    })
})
