import { describe, test, expect, beforeEach, afterEach, mock } from 'bun:test'

// Type definitions for tests
interface Sbom {
  id: string
  name: string
  format?: string
  format_version?: string
  version?: string
  created_at?: string
}

interface SbomData {
  sbom: Sbom
  has_vulnerabilities_report: boolean
}



// Mock DOM environment for testing
const mockSessionStorage = {
  store: {} as { [key: string]: string },
  get length(): number {
    return Object.keys(this.store).length
  },
  getItem(key: string): string | null {
    return this.store[key] || null
  },
  setItem(key: string, value: string): void {
    this.store[key] = value
  },
  removeItem(key: string): void {
    delete this.store[key]
  },
  key(index: number): string | null {
    const keys = Object.keys(this.store)
    return keys[index] || null
  },
  clear(): void {
    this.store = {}
  }
}

// Mock DOM methods
const mockDocument = {
  getElementById: (id: string) => {
    const mockElements: { [key: string]: { textContent: string } } = {
      'valid-json-data': { textContent: JSON.stringify([
        {
          sbom: {
            id: 'sbom-1',
            name: 'Test SBOM 1',
            format: 'cyclonedx',
            format_version: '1.5',
            version: '1.0.0',
            created_at: '2024-01-01T00:00:00Z'
          },
          has_vulnerabilities_report: true
        },
        {
          sbom: {
            id: 'sbom-2',
            name: 'Test SBOM 2',
            format: 'spdx',
            format_version: '2.3',
            version: '2.0.0',
            created_at: '2024-01-02T00:00:00Z'
          },
          has_vulnerabilities_report: false
        }
      ]) },
      'empty-array-data': { textContent: '[]' },
      'invalid-json-data': { textContent: 'invalid json' },
      'non-array-data': { textContent: '{"not": "array"}' }
    }
    return mockElements[id] || null
  }
}

// Set up global mocks
global.sessionStorage = mockSessionStorage as unknown as Storage
global.document = mockDocument as unknown as Document

describe('SbomsTable Business Logic', () => {
  beforeEach(() => {
    sessionStorage.clear()
  })

  afterEach(() => {
    sessionStorage.clear()
  })

  describe('Data Parsing', () => {
    test('should parse valid SBOM data from JSON script element', () => {
      const parseSbomsData = (elementId?: string) => {
        try {
          if (elementId) {
            const element = document.getElementById(elementId)
            if (element && element.textContent) {
              const parsed = JSON.parse(element.textContent)
              if (Array.isArray(parsed)) {
                return { success: true, data: parsed, error: null }
              }
            }
          }
          return { success: false, data: [], error: null }
        } catch (err) {
          return {
            success: false,
            data: [],
            error: err instanceof Error ? err.message : 'Failed to parse SBOMs data'
          }
        }
      }

      const result = parseSbomsData('valid-json-data')
      expect(result.success).toBe(true)
      expect(result.data).toHaveLength(2)
      expect(result.data[0].sbom.name).toBe('Test SBOM 1')
      expect(result.data[1].sbom.format).toBe('spdx')
      expect(result.error).toBe(null)
    })

    test('should handle empty array data', () => {
      const parseSbomsData = (elementId?: string) => {
        try {
          if (elementId) {
            const element = document.getElementById(elementId)
            if (element && element.textContent) {
              const parsed = JSON.parse(element.textContent)
              if (Array.isArray(parsed)) {
                return { success: true, data: parsed, error: null }
              }
            }
          }
          return { success: false, data: [], error: null }
        } catch (err) {
          return {
            success: false,
            data: [],
            error: err instanceof Error ? err.message : 'Failed to parse SBOMs data'
          }
        }
      }

      const result = parseSbomsData('empty-array-data')
      expect(result.success).toBe(true)
      expect(result.data).toHaveLength(0)
      expect(result.error).toBe(null)
    })

    test('should handle invalid JSON data', () => {
      const parseSbomsData = (elementId?: string) => {
        try {
          if (elementId) {
            const element = document.getElementById(elementId)
            if (element && element.textContent) {
              const parsed = JSON.parse(element.textContent)
              if (Array.isArray(parsed)) {
                return { success: true, data: parsed, error: null }
              }
            }
          }
          return { success: false, data: [], error: null }
        } catch (err) {
          return {
            success: false,
            data: [],
            error: err instanceof Error ? err.message : 'Failed to parse SBOMs data'
          }
        }
      }

      const result = parseSbomsData('invalid-json-data')
      expect(result.success).toBe(false)
      expect(result.data).toHaveLength(0)
      expect(result.error).toContain('JSON Parse error')
    })

    test('should handle non-array JSON data', () => {
      const parseSbomsData = (elementId?: string) => {
        try {
          if (elementId) {
            const element = document.getElementById(elementId)
            if (element && element.textContent) {
              const parsed = JSON.parse(element.textContent)
              if (Array.isArray(parsed)) {
                return { success: true, data: parsed, error: null }
              }
            }
          }
          return { success: false, data: [], error: null }
        } catch (err) {
          return {
            success: false,
            data: [],
            error: err instanceof Error ? err.message : 'Failed to parse SBOMs data'
          }
        }
      }

      const result = parseSbomsData('non-array-data')
      expect(result.success).toBe(false)
      expect(result.data).toHaveLength(0)
      expect(result.error).toBe(null)
    })

    test('should handle missing element ID', () => {
      const parseSbomsData = (elementId?: string) => {
        try {
          if (elementId) {
            const element = document.getElementById(elementId)
            if (element && element.textContent) {
              const parsed = JSON.parse(element.textContent)
              if (Array.isArray(parsed)) {
                return { success: true, data: parsed, error: null }
              }
            }
          }
          return { success: false, data: [], error: null }
        } catch (err) {
          return {
            success: false,
            data: [],
            error: err instanceof Error ? err.message : 'Failed to parse SBOMs data'
          }
        }
      }

      const result = parseSbomsData('non-existent-element')
      expect(result.success).toBe(false)
      expect(result.data).toHaveLength(0)
      expect(result.error).toBe(null)
    })
  })

  describe('Data Formatting', () => {
    test('should truncate text correctly', () => {
      const truncateText = (text: string, maxLength: number): string => {
        if (text.length <= maxLength) return text
        return text.substring(0, maxLength - 3) + '...'
      }

      expect(truncateText('Short text', 20)).toBe('Short text')
      expect(truncateText('This is a very long text that exceeds the limit', 20)).toBe('This is a very lo...')
      expect(truncateText('Exactly twenty chars', 20)).toBe('Exactly twenty chars')
      expect(truncateText('Twenty one characters', 20)).toBe('Twenty one charac...')
    })

    test('should format dates correctly', () => {
      const formatDate = (dateString: string): string => {
        try {
          const date = new Date(dateString)
          const formatted = date.toLocaleDateString()
          // Check if the date is invalid
          if (formatted === 'Invalid Date') {
            return dateString
          }
          return formatted
        } catch {
          return dateString
        }
      }

      expect(formatDate('2024-01-01T00:00:00Z')).toMatch(/\d{1,2}\/\d{1,2}\/\d{4}/)
      expect(formatDate('invalid-date')).toBe('invalid-date')
      expect(formatDate('')).toBe('')
    })
  })

  describe('SBOM Format Display', () => {
    test('should display correct format labels', () => {
      const getFormatDisplay = (format: string): string => {
        switch (format) {
          case 'spdx': return 'SPDX'
          case 'cyclonedx': return 'CycloneDX'
          default: return format
        }
      }

      expect(getFormatDisplay('spdx')).toBe('SPDX')
      expect(getFormatDisplay('cyclonedx')).toBe('CycloneDX')
      expect(getFormatDisplay('unknown')).toBe('unknown')
      expect(getFormatDisplay('')).toBe('')
    })
  })

  describe('URL Generation', () => {
    test('should generate correct SBOM URLs', () => {
      const generateSbomUrls = (sbomId: string) => ({
        details: `/sboms/${sbomId}/`,
        download: `/sboms/${sbomId}/download/`,
        vulnerabilities: `/sboms/${sbomId}/vulnerabilities/`
      })

      const urls = generateSbomUrls('test-sbom-123')
      expect(urls.details).toBe('/sboms/test-sbom-123/')
      expect(urls.download).toBe('/sboms/test-sbom-123/download/')
      expect(urls.vulnerabilities).toBe('/sboms/test-sbom-123/vulnerabilities/')
    })

    test('should generate correct URLs for public vs private views', () => {
      const getSbomDetailUrl = (sbomId: string, isPublic: boolean): string => {
        if (isPublic) {
          return `/public/sbom/${sbomId}/`
        }
        return `/sbom/${sbomId}/`
      }

      const getSbomDownloadUrl = (sbomId: string): string => {
        return `/sbom/download/${sbomId}`
      }

      const sbomId = 'test-sbom-456'

      // Test private URLs
      expect(getSbomDetailUrl(sbomId, false)).toBe('/sbom/test-sbom-456/')
      expect(getSbomDownloadUrl(sbomId)).toBe('/sbom/download/test-sbom-456')

      // Test public URLs
      expect(getSbomDetailUrl(sbomId, true)).toBe('/public/sbom/test-sbom-456/')
      expect(getSbomDownloadUrl(sbomId)).toBe('/sbom/download/test-sbom-456') // Same for both
    })
  })

  describe('Vulnerability Button State', () => {
    test('should determine correct button classes', () => {
      const getVulnButtonClasses = (hasReport: boolean): string[] => {
        return ['btn', 'btn-sm', 'btn-warning', ...(hasReport ? [] : ['disabled'])]
      }

      expect(getVulnButtonClasses(true)).toEqual(['btn', 'btn-sm', 'btn-warning'])
      expect(getVulnButtonClasses(false)).toEqual(['btn', 'btn-sm', 'btn-warning', 'disabled'])
    })
  })

  describe('Data State Management', () => {
    test('should correctly determine if data exists', () => {
      const hasData = (data: unknown[]): boolean => data.length > 0

      expect(hasData([])).toBe(false)
      expect(hasData([{ test: 'data' }])).toBe(true)
      expect(hasData([1, 2, 3])).toBe(true)
    })

    test('should handle error states', () => {
      interface ComponentState {
        data: unknown[]
        error: string | null
        hasData: boolean
        hasError: boolean
      }

      const createState = (data: unknown[], error: string | null): ComponentState => ({
        data,
        error,
        hasData: data.length > 0,
        hasError: error !== null
      })

      const successState = createState([{ test: 'data' }], null)
      expect(successState.hasData).toBe(true)
      expect(successState.hasError).toBe(false)

      const errorState = createState([], 'Failed to load data')
      expect(errorState.hasData).toBe(false)
      expect(errorState.hasError).toBe(true)

      const emptyState = createState([], null)
      expect(emptyState.hasData).toBe(false)
      expect(emptyState.hasError).toBe(false)
    })
  })

  describe('Integration Scenarios', () => {
    test('should handle complete data processing workflow', () => {
      const processData = (elementId?: string) => {
        let parsedData: unknown[] = []
        let error: string | null = null

        try {
          if (elementId) {
            const element = document.getElementById(elementId)
            if (element && element.textContent) {
              const parsed = JSON.parse(element.textContent)
              if (Array.isArray(parsed)) {
                parsedData = parsed
              }
            }
          }
        } catch (err) {
          error = err instanceof Error ? err.message : 'Failed to parse data'
          parsedData = []
        }

        return {
          data: parsedData,
          error,
          hasData: parsedData.length > 0,
          hasError: error !== null
        }
      }

      // Test successful data processing
      const successResult = processData('valid-json-data')
      expect(successResult.hasData).toBe(true)
      expect(successResult.hasError).toBe(false)
      expect(successResult.data).toHaveLength(2)

      // Test error handling
      const errorResult = processData('invalid-json-data')
      expect(errorResult.hasData).toBe(false)
      expect(errorResult.hasError).toBe(true)
      expect(errorResult.error).toContain('JSON Parse error')

      // Test empty data
      const emptyResult = processData('empty-array-data')
      expect(emptyResult.hasData).toBe(false)
      expect(emptyResult.hasError).toBe(false)
      expect(emptyResult.data).toHaveLength(0)
    })
  })

  describe('Delete Modal Functionality', () => {
    test('should manage modal state correctly', () => {
      // Mock modal state management
      let showDeleteModal = false
      let sbomToDelete: Sbom | null = null
      let isDeleting: string | null = null

      const confirmDelete = (sbom: Sbom): void => {
        sbomToDelete = sbom
        showDeleteModal = true
      }

      const cancelDelete = (): void => {
        if (isDeleting) return // Prevent canceling during deletion
        showDeleteModal = false
        sbomToDelete = null
      }

      const testSbom = {
        id: 'sbom-1',
        name: 'test-sbom',
        format: 'spdx',
        format_version: '2.3',
        version: '1.0.0',
        created_at: '2024-01-01T00:00:00Z'
      }

      // Test opening modal
      expect(showDeleteModal).toBe(false)
      expect(sbomToDelete).toBe(null)

      confirmDelete(testSbom)
      expect(showDeleteModal).toBe(true)
      expect(sbomToDelete).toBe(testSbom)

      // Test closing modal
      cancelDelete()
      expect(showDeleteModal).toBe(false)
      expect(sbomToDelete).toBe(null)

      // Test preventing close during deletion
      confirmDelete(testSbom)
      isDeleting = 'sbom-1'
      cancelDelete() // Should not close
      expect(showDeleteModal).toBe(true)
      expect(sbomToDelete).toBe(testSbom)

      // Clear deleting state and try again
      isDeleting = null
      cancelDelete()
      expect(showDeleteModal).toBe(false)
      expect(sbomToDelete).toBe(null)
    })

    test('should handle keyboard navigation', () => {
      let modalClosed = false
      let deleteTriggered = false

      const handleKeydown = (event: { key: string; preventDefault: () => void }): void => {
        if (event.key === 'Escape') {
          event.preventDefault()
          modalClosed = true
        } else if (event.key === 'Enter') {
          event.preventDefault()
          deleteTriggered = true
        }
      }

            // Test Escape key
      const escapeEvent = {
        key: 'Escape',
        preventDefault: mock()
      }
      handleKeydown(escapeEvent)
      expect(modalClosed).toBe(true)
      expect(escapeEvent.preventDefault).toHaveBeenCalled()

      // Reset and test Enter key
      modalClosed = false
      deleteTriggered = false
      const enterEvent = {
        key: 'Enter',
        preventDefault: mock()
      }
      handleKeydown(enterEvent)
      expect(deleteTriggered).toBe(true)
      expect(enterEvent.preventDefault).toHaveBeenCalled()

      // Test other keys (should do nothing)
      modalClosed = false
      deleteTriggered = false
      const otherEvent = {
        key: 'Tab',
        preventDefault: mock()
      }
      handleKeydown(otherEvent)
      expect(modalClosed).toBe(false)
      expect(deleteTriggered).toBe(false)
      expect(otherEvent.preventDefault).not.toHaveBeenCalled()
    })
  })

  describe('Delete API Integration', () => {
    test('should handle successful deletion', async () => {
      // Mock API and utilities
      const mockAxios = {
        delete: mock()
      }
      mockAxios.delete.mockResolvedValue({ status: 204 })

      const mockShowSuccess = mock()
      const mockShowError = mock()

      let sbomsData = [
        {
          sbom: {
            id: 'sbom-1',
            name: 'test-sbom-1',
            format: 'spdx',
            format_version: '2.3',
            version: '1.0.0',
            created_at: '2024-01-01T00:00:00Z'
          },
          has_vulnerabilities_report: true
        },
        {
          sbom: {
            id: 'sbom-2',
            name: 'test-sbom-2',
            format: 'cyclonedx',
            format_version: '1.6',
            version: '2.0.0',
            created_at: '2024-01-02T00:00:00Z'
          },
          has_vulnerabilities_report: false
        }
      ]

      let showDeleteModal = true
      let sbomToDelete = sbomsData[0].sbom
      let isDeleting: string | null = null

      const deleteSbom = async (): Promise<void> => {
        if (!sbomToDelete) return

        isDeleting = sbomToDelete.id

        try {
          await mockAxios.delete(`/api/v1/sboms/sbom/${sbomToDelete.id}`)

          // Remove the deleted SBOM from the list
          sbomsData = sbomsData.filter(
            item => item.sbom.id !== sbomToDelete!.id
          )

          mockShowSuccess(`SBOM "${sbomToDelete.name}" deleted successfully`)

          // Clear deleting state before closing modal
          isDeleting = null
          showDeleteModal = false
          sbomToDelete = null
        } catch (err: unknown) {
          let errorMessage = 'Failed to delete SBOM'
          if (err && typeof err === 'object' && 'response' in err) {
            const apiError = err as { response?: { data?: { detail?: string } } }
            if (apiError.response?.data?.detail) {
              errorMessage = apiError.response.data.detail
            }
          }
          mockShowError(errorMessage)
          isDeleting = null
        }
      }

      // Execute deletion
      await deleteSbom()

      // Verify API call
      expect(mockAxios.delete).toHaveBeenCalledWith('/api/v1/sboms/sbom/sbom-1')

      // Verify success message
      expect(mockShowSuccess).toHaveBeenCalledWith('SBOM "test-sbom-1" deleted successfully')

      // Verify SBOM removal
      expect(sbomsData).toHaveLength(1)
      expect(sbomsData[0].sbom.id).toBe('sbom-2')

      // Verify modal closed
      expect(showDeleteModal).toBe(false)
      expect(sbomToDelete).toBe(null)
      expect(isDeleting).toBe(null)
    })

    test('should handle deletion errors', async () => {
      const mockAxios = {
        delete: mock(() => Promise.reject({
          response: { data: { detail: 'Permission denied' } }
        }))
      }
      const mockShowSuccess = mock()
      const mockShowError = mock()

      let sbomsData = [
        {
          sbom: {
            id: 'sbom-1',
            name: 'test-sbom-1',
            format: 'spdx',
            format_version: '2.3',
            version: '1.0.0',
            created_at: '2024-01-01T00:00:00Z'
          },
          has_vulnerabilities_report: true
        }
      ]

      let showDeleteModal = true
      let sbomToDelete = sbomsData[0].sbom
      let isDeleting: string | null = null

      const deleteSbom = async (): Promise<void> => {
        if (!sbomToDelete) return

        isDeleting = sbomToDelete.id

        try {
          await mockAxios.delete(`/api/v1/sboms/sbom/${sbomToDelete.id}`)

          // Remove the deleted SBOM from the list
          sbomsData = sbomsData.filter(
            item => item.sbom.id !== sbomToDelete!.id
          )

          mockShowSuccess(`SBOM "${sbomToDelete.name}" deleted successfully`)

          // Clear deleting state before closing modal
          isDeleting = null
          showDeleteModal = false
          sbomToDelete = null
        } catch (err: unknown) {
          let errorMessage = 'Failed to delete SBOM'
          if (err && typeof err === 'object' && 'response' in err) {
            const apiError = err as { response?: { data?: { detail?: string } } }
            if (apiError.response?.data?.detail) {
              errorMessage = apiError.response.data.detail
            }
          }
          mockShowError(errorMessage)
          isDeleting = null
        }
      }

      // Execute deletion
      await deleteSbom()

      // Verify API call
      expect(mockAxios.delete).toHaveBeenCalledWith('/api/v1/sboms/sbom/sbom-1')

      // Verify error message
      expect(mockShowError).toHaveBeenCalledWith('Permission denied')

      // Verify SBOM not removed
      expect(sbomsData).toHaveLength(1)
      expect(sbomsData[0].sbom.id).toBe('sbom-1')

      // Verify modal still open (since deletion failed)
      expect(showDeleteModal).toBe(true)
      expect(sbomToDelete).not.toBe(null)
      expect(isDeleting).toBe(null) // Should be cleared even on error
    })

    test('should handle non-response errors', async () => {
      const mockAxios = {
        delete: mock(() => Promise.reject(new Error('Network error')))
      }
      const mockShowError = mock()

      let sbomToDelete = {
        id: 'sbom-1',
        name: 'test-sbom-1'
      }
      let isDeleting: string | null = null

      const deleteSbom = async (): Promise<void> => {
        if (!sbomToDelete) return

        isDeleting = sbomToDelete.id

        try {
          await mockAxios.delete(`/api/v1/sboms/sbom/${sbomToDelete.id}`)
          // ... success logic
        } catch (err: unknown) {
          let errorMessage = 'Failed to delete SBOM'
          if (err && typeof err === 'object' && 'response' in err) {
            const apiError = err as { response?: { data?: { detail?: string } } }
            if (apiError.response?.data?.detail) {
              errorMessage = apiError.response.data.detail
            }
          }
          mockShowError(errorMessage)
          isDeleting = null
        }
      }

      await deleteSbom()

      expect(mockShowError).toHaveBeenCalledWith('Failed to delete SBOM')
      expect(isDeleting).toBe(null)
    })
  })

  describe('Permission Management', () => {
    test('should correctly parse CRUD permissions', () => {
      const hasCrudPermissions = (permissionString?: string): boolean => {
        return permissionString === 'true'
      }

      expect(hasCrudPermissions('true')).toBe(true)
      expect(hasCrudPermissions('false')).toBe(false)
      expect(hasCrudPermissions('')).toBe(false)
      expect(hasCrudPermissions(undefined)).toBe(false)
      expect(hasCrudPermissions('TRUE')).toBe(false) // Case sensitive
      expect(hasCrudPermissions('1')).toBe(false)
    })

    test('should determine UI element visibility based on permissions', () => {
      const shouldShowActions = (hasCrud: boolean): boolean => hasCrud
      const shouldShowDeleteButton = (hasCrud: boolean): boolean => hasCrud

      // With permissions
      expect(shouldShowActions(true)).toBe(true)
      expect(shouldShowDeleteButton(true)).toBe(true)

      // Without permissions
      expect(shouldShowActions(false)).toBe(false)
      expect(shouldShowDeleteButton(false)).toBe(false)
    })
  })

  describe('Loading State Management', () => {
    test('should manage deletion loading states', () => {
      let isDeleting: string | null = null

      const startDeleting = (sbomId: string): void => {
        isDeleting = sbomId
      }

      const stopDeleting = (): void => {
        isDeleting = null
      }

      const isCurrentlyDeleting = (sbomId: string): boolean => {
        return isDeleting === sbomId
      }

      // Initial state
      expect(isDeleting).toBe(null)
      expect(isCurrentlyDeleting('sbom-1')).toBe(false)

      // Start deleting
      startDeleting('sbom-1')
      expect(isDeleting).toBe('sbom-1')
      expect(isCurrentlyDeleting('sbom-1')).toBe(true)
      expect(isCurrentlyDeleting('sbom-2')).toBe(false)

      // Stop deleting
      stopDeleting()
      expect(isDeleting).toBe(null)
      expect(isCurrentlyDeleting('sbom-1')).toBe(false)
    })

    test('should determine button states during loading', () => {
      const getButtonState = (sbomId: string, isDeleting: string | null) => ({
        disabled: isDeleting === sbomId,
        showSpinner: isDeleting === sbomId,
        showTrashIcon: isDeleting !== sbomId
      })

      // Not deleting
      let state = getButtonState('sbom-1', null)
      expect(state.disabled).toBe(false)
      expect(state.showSpinner).toBe(false)
      expect(state.showTrashIcon).toBe(true)

      // Deleting this SBOM
      state = getButtonState('sbom-1', 'sbom-1')
      expect(state.disabled).toBe(true)
      expect(state.showSpinner).toBe(true)
      expect(state.showTrashIcon).toBe(false)

      // Deleting different SBOM
      state = getButtonState('sbom-1', 'sbom-2')
      expect(state.disabled).toBe(false)
      expect(state.showSpinner).toBe(false)
      expect(state.showTrashIcon).toBe(true)
    })
  })

  describe('Data List Management', () => {
    test('should remove items from list correctly', () => {
      let sbomsData = [
        { sbom: { id: 'sbom-1', name: 'SBOM 1' } },
        { sbom: { id: 'sbom-2', name: 'SBOM 2' } },
        { sbom: { id: 'sbom-3', name: 'SBOM 3' } }
      ]

      const removeFromList = (sbomId: string) => {
        sbomsData = sbomsData.filter(item => item.sbom.id !== sbomId)
      }

      expect(sbomsData).toHaveLength(3)

      // Remove middle item
      removeFromList('sbom-2')
      expect(sbomsData).toHaveLength(2)
      expect(sbomsData.map(item => item.sbom.id)).toEqual(['sbom-1', 'sbom-3'])

      // Remove first item
      removeFromList('sbom-1')
      expect(sbomsData).toHaveLength(1)
      expect(sbomsData[0].sbom.id).toBe('sbom-3')

      // Remove last item
      removeFromList('sbom-3')
      expect(sbomsData).toHaveLength(0)

      // Try to remove from empty list (should not error)
      removeFromList('non-existent')
      expect(sbomsData).toHaveLength(0)
    })

    test('should handle empty state after all deletions', () => {
      let sbomsData: SbomData[] = []

      const hasData = (): boolean => sbomsData.length > 0
      const shouldShowEmptyState = (): boolean => !hasData()

      expect(hasData()).toBe(false)
      expect(shouldShowEmptyState()).toBe(true)

      // Add some data
      sbomsData = [{
        sbom: {
          id: 'sbom-1',
          name: 'Test SBOM',
          format: 'cyclonedx',
          format_version: '1.6',
          version: '1.0.0',
          created_at: '2024-01-01T00:00:00Z'
        },
        has_vulnerabilities_report: false
      }]
      expect(hasData()).toBe(true)
      expect(shouldShowEmptyState()).toBe(false)

      // Remove all data
      sbomsData = []
      expect(hasData()).toBe(false)
      expect(shouldShowEmptyState()).toBe(true)
    })
  })
})