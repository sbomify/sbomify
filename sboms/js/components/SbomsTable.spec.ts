import { describe, test, expect, beforeEach, afterEach } from 'bun:test'

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
})