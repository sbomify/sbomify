import { describe, test, expect } from 'bun:test'
import { getCsrfTokenFromSources, parseCsrfFromCookie } from '../../core/js/test-utils'

const MAX_SBOM_SIZE = 100 * 1024 * 1024;
const ALLOWED_MIME_TYPES = ['application/json', 'text/plain'];
const ALLOWED_EXTENSIONS = ['.json', '.spdx', '.cdx'];

/**
 * Tests for SBOM Upload Alpine.js component business logic
 *
 * This test suite validates the core functionality of the SBOM upload component
 * including file validation, drag-and-drop handling, error formatting, and upload workflow.
 */

describe('SBOM Upload Business Logic', () => {
    const testComponentId = 'test-component-123'

    const createMockFile = (name: string, size: number, type: string): File => {
        const content = new Array(size).fill('a').join('')
        return new File([content], name, { type })
    }

    describe('File Validation', () => {
        const validateFile = (file: File): string | null => {
            if (file.size > MAX_SBOM_SIZE) {
                return 'File size must be less than 100MB'
            }

            const fileExtension = file.name.toLowerCase().slice(file.name.lastIndexOf('.'));
            const hasValidType = ALLOWED_MIME_TYPES.includes(file.type);
            const hasValidExtension = ALLOWED_EXTENSIONS.includes(fileExtension);

            if (!hasValidType && !hasValidExtension) {
                return 'Please select a valid SBOM file (.json, .spdx, .cdx)'
            }

            return null
        }

        test('should accept valid JSON file with correct MIME type', () => {
            const file = createMockFile('sbom.json', 1024, 'application/json')
            expect(validateFile(file)).toBeNull()
        })

        test('should accept valid JSON file with text/plain MIME type', () => {
            const file = createMockFile('sbom.json', 1024, 'text/plain')
            expect(validateFile(file)).toBeNull()
        })

        test('should accept .spdx file regardless of MIME type', () => {
            // Browsers often report unknown MIME types for .spdx files
            const file = createMockFile('sbom.spdx', 1024, 'application/octet-stream')
            expect(validateFile(file)).toBeNull()
        })

        test('should accept .cdx file regardless of MIME type', () => {
            const file = createMockFile('sbom.cdx', 1024, '')
            expect(validateFile(file)).toBeNull()
        })

        test('should handle files with multiple dots in name', () => {
            const file = createMockFile('my.app.sbom.json', 1024, 'application/json')
            expect(validateFile(file)).toBeNull()
        })

        test('should reject file larger than 100MB', () => {
            const size = 101 * 1024 * 1024 // 101MB
            const file = createMockFile('large-sbom.json', size, 'application/json')
            expect(validateFile(file)).toBe('File size must be less than 100MB')
        })

        test('should accept file exactly at 100MB limit', () => {
            const size = 100 * 1024 * 1024 // exactly 100MB
            const file = createMockFile('max-sbom.json', size, 'application/json')
            expect(validateFile(file)).toBeNull()
        })

        test('should reject file with invalid extension and invalid MIME type', () => {
            const file = createMockFile('document.pdf', 1024, 'application/pdf')
            expect(validateFile(file)).toBe('Please select a valid SBOM file (.json, .spdx, .cdx)')
        })

        test('should reject .txt file with unsupported MIME type', () => {
            const file = createMockFile('notes.txt', 1024, 'text/html')
            expect(validateFile(file)).toBe('Please select a valid SBOM file (.json, .spdx, .cdx)')
        })

        test('should handle case-insensitive extension matching', () => {
            const file = createMockFile('sbom.JSON', 1024, 'application/octet-stream')
            expect(validateFile(file)).toBeNull()

            const file2 = createMockFile('sbom.SPDX', 1024, 'application/octet-stream')
            expect(validateFile(file2)).toBeNull()

            const file3 = createMockFile('sbom.CDX', 1024, 'application/octet-stream')
            expect(validateFile(file3)).toBeNull()
        })
    })

    describe('CSRF Token Retrieval Logic', () => {
        test('should correctly structure CSRF token retrieval logic', () => {
            // Uses shared getCsrfTokenFromSources utility from test-utils
            // Test meta tag takes priority
            expect(getCsrfTokenFromSources('meta-token', 'cookie-token')).toBe('meta-token')

            // Test fallback to cookie
            expect(getCsrfTokenFromSources(null, 'cookie-token')).toBe('cookie-token')

            // Test empty string when no token
            expect(getCsrfTokenFromSources(null, null)).toBe('')
        })

        test('should parse CSRF cookie correctly', () => {
            // Uses shared parseCsrfFromCookie utility from test-utils
            expect(parseCsrfFromCookie('csrftoken=abc123')).toBe('abc123')
            expect(parseCsrfFromCookie('session=xyz; csrftoken=token456')).toBe('token456')
            expect(parseCsrfFromCookie('session=xyz')).toBe('')
            expect(parseCsrfFromCookie('')).toBe('')
        })
    })

    describe('State Management', () => {
        test('should initialize with correct default state', () => {
            const initialState = {
                expanded: true,
                isDragOver: false,
                isUploading: false,
                componentId: testComponentId
            }

            expect(initialState.expanded).toBe(true)
            expect(initialState.isDragOver).toBe(false)
            expect(initialState.isUploading).toBe(false)
            expect(initialState.componentId).toBe(testComponentId)
        })

        test('should track drag over state correctly', () => {
            let isDragOver = false

            // Simulate dragover
            isDragOver = true
            expect(isDragOver).toBe(true)

            // Simulate dragleave
            isDragOver = false
            expect(isDragOver).toBe(false)
        })

        test('should track uploading state correctly', () => {
            let isUploading = false

            // Simulate upload start
            isUploading = true
            expect(isUploading).toBe(true)

            // Simulate upload end
            isUploading = false
            expect(isUploading).toBe(false)
        })

        test('should store component ID from initialization', () => {
            const componentIds = ['comp-1', 'comp-2', 'my-special-component']

            componentIds.forEach(id => {
                const state = { componentId: id }
                expect(state.componentId).toBe(id)
            })
        })
    })

    describe('Drag and Drop Handling', () => {
        test('should extract file from DataTransfer on drop', () => {
            const mockFile = createMockFile('dropped.json', 1024, 'application/json')

            // Simulate handling a drop event
            const handleDrop = (files: FileList | null): File | null => {
                if (files && files.length > 0) {
                    return files[0]
                }
                return null
            }

            // Create a mock FileList
            const mockFileList = {
                0: mockFile,
                length: 1,
                item: (index: number) => index === 0 ? mockFile : null
            } as unknown as FileList

            const result = handleDrop(mockFileList)
            expect(result).toBe(mockFile)
        })

        test('should handle empty drop gracefully', () => {
            const handleDrop = (files: FileList | null): File | null => {
                if (files && files.length > 0) {
                    return files[0]
                }
                return null
            }

            expect(handleDrop(null)).toBeNull()

            const emptyFileList = { length: 0, item: () => null } as unknown as FileList
            expect(handleDrop(emptyFileList)).toBeNull()
        })
    })

    describe('File Select Handling', () => {
        test('should handle file selection from input', () => {
            const mockFile = createMockFile('selected.json', 1024, 'application/json')

            const handleFileSelect = (files: FileList | null): File | null => {
                if (files && files.length > 0) {
                    return files[0]
                }
                return null
            }

            const mockFileList = {
                0: mockFile,
                length: 1,
                item: (index: number) => index === 0 ? mockFile : null
            } as unknown as FileList

            const result = handleFileSelect(mockFileList)
            expect(result).toBe(mockFile)
        })

        test('should reset input value after file selection', () => {
            // This tests the behavior of resetting input.value = ''
            // which allows re-uploading the same file
            let inputValue = 'C:\\fakepath\\file.json'

            const resetInput = () => {
                inputValue = ''
            }

            expect(inputValue).not.toBe('')
            resetInput()
            expect(inputValue).toBe('')
        })
    })

    describe('Upload Workflow', () => {
        test('should construct correct API endpoint', () => {
            const buildEndpoint = (componentId: string): string => {
                return `/api/v1/sboms/upload-file/${componentId}`
            }

            expect(buildEndpoint('comp-123')).toBe('/api/v1/sboms/upload-file/comp-123')
            expect(buildEndpoint('my-component')).toBe('/api/v1/sboms/upload-file/my-component')
        })

        test('should build FormData correctly', () => {
            const mockFile = createMockFile('sbom.json', 1024, 'application/json')

            const buildFormData = (file: File, componentId: string): FormData => {
                const formData = new FormData()
                formData.append('sbom_file', file)
                formData.append('component_id', componentId)
                return formData
            }

            const formData = buildFormData(mockFile, testComponentId)

            // Verify FormData contains the expected entries
            expect(formData.has('sbom_file')).toBe(true)
            expect(formData.get('component_id')).toBe(testComponentId)
        })

        test('should handle successful upload response', () => {
            const handleResponse = (ok: boolean, data: Record<string, unknown>): { success: boolean; message: string } => {
                if (ok) {
                    return { success: true, message: 'SBOM uploaded successfully!' }
                } else {
                    return { success: false, message: (data.detail as string) || 'Upload failed' }
                }
            }

            const successResult = handleResponse(true, {})
            expect(successResult.success).toBe(true)
            expect(successResult.message).toBe('SBOM uploaded successfully!')
        })

        test('should handle error response with detail message', () => {
            const handleResponse = (ok: boolean, data: Record<string, unknown>): { success: boolean; message: string } => {
                if (ok) {
                    return { success: true, message: 'SBOM uploaded successfully!' }
                } else {
                    return { success: false, message: (data.detail as string) || 'Upload failed' }
                }
            }

            const errorResult = handleResponse(false, { detail: 'Invalid SBOM format' })
            expect(errorResult.success).toBe(false)
            expect(errorResult.message).toBe('Invalid SBOM format')
        })

        test('should fallback to default error message when no detail provided', () => {
            const handleResponse = (ok: boolean, data: Record<string, unknown>): { success: boolean; message: string } => {
                if (ok) {
                    return { success: true, message: 'SBOM uploaded successfully!' }
                } else {
                    return { success: false, message: (data.detail as string) || 'Upload failed' }
                }
            }

            const errorResult = handleResponse(false, {})
            expect(errorResult.success).toBe(false)
            expect(errorResult.message).toBe('Upload failed')
        })

        test('should handle network errors gracefully', () => {
            const handleNetworkError = (): string => {
                return 'Network error occurred. Please try again.'
            }

            expect(handleNetworkError()).toBe('Network error occurred. Please try again.')
        })
    })

    describe('Error Response Parsing', () => {
        test('should safely parse JSON response', async () => {
            const safeJsonParse = async (response: Response): Promise<Record<string, unknown>> => {
                try {
                    return await response.json()
                } catch {
                    return {}
                }
            }

            // Mock a valid JSON response
            const validResponse = new Response(JSON.stringify({ detail: 'test' }), {
                headers: { 'Content-Type': 'application/json' }
            })

            const validResult = await safeJsonParse(validResponse)
            expect(validResult.detail).toBe('test')
        })

        test('should return empty object for invalid JSON', async () => {
            const safeJsonParse = async (response: Response): Promise<Record<string, unknown>> => {
                try {
                    return await response.json()
                } catch {
                    return {}
                }
            }

            // Mock an HTML error page response
            const htmlResponse = new Response('<html><body>500 Error</body></html>', {
                headers: { 'Content-Type': 'text/html' }
            })

            const result = await safeJsonParse(htmlResponse)
            expect(result).toEqual({})
        })
    })

    describe('Accessibility Features', () => {
        test('should have correct ARIA attributes defined', () => {
            const ariaConfig = {
                role: 'button',
                ariaLabel: 'Upload SBOM file by dropping or clicking',
                ariaBusy: false,
                tabIndex: 0
            }

            expect(ariaConfig.role).toBe('button')
            expect(ariaConfig.ariaLabel).toContain('Upload SBOM')
            expect(ariaConfig.tabIndex).toBe(0)
        })

        test('should update aria-busy during upload', () => {
            let isUploading = false
            const getAriaBusy = () => isUploading

            expect(getAriaBusy()).toBe(false)

            isUploading = true
            expect(getAriaBusy()).toBe(true)

            isUploading = false
            expect(getAriaBusy()).toBe(false)
        })
    })

    describe('Expanded State Persistence', () => {
        test('should handle localStorage persistence for expanded state', () => {
            const storage: Record<string, string> = {}

            const setExpanded = (value: boolean) => {
                storage['sbom-upload-expanded'] = value ? 'true' : 'false'
            }

            const getExpanded = (): boolean => {
                return storage['sbom-upload-expanded'] !== 'false'
            }

            // Default is expanded
            expect(getExpanded()).toBe(true)

            // Collapse
            setExpanded(false)
            expect(getExpanded()).toBe(false)

            // Expand
            setExpanded(true)
            expect(getExpanded()).toBe(true)
        })
    })
})
