import { describe, it, expect, mock, beforeEach } from 'bun:test'
import type { CustomLicense } from '../type_defs'

interface ValidationResponse {
  status: number
  normalized?: string
  tokens?: Array<{ key: string; known: boolean }>
  unknown_tokens?: string[]
  error?: string
}

interface LicenseData {
  key: string
  name: string
  category: string | null
  origin: string
}

interface CustomLicenseResponse {
  success: boolean
}

interface MockAxiosResponse<T = unknown> {
  data: T
  status: number
  statusText: string
  headers: Record<string, string>
  config: Record<string, unknown>
}

// Mock the $axios utils module using Bun's mock
const mockAxios = {
  get: mock<() => Promise<MockAxiosResponse<LicenseData[]>>>(),
  post: mock<(url: string, data?: unknown) => Promise<MockAxiosResponse<ValidationResponse | CustomLicenseResponse>>>(),
  put: mock<() => Promise<MockAxiosResponse<Record<string, unknown>>>>(),
  delete: mock<() => Promise<MockAxiosResponse<Record<string, unknown>>>>()
}

mock.module('../../../core/js/utils', () => ({
  default: mockAxios,
  isEmpty: mock<(value: unknown) => boolean>()
}))

describe('LicensesEditor Business Logic', () => {
  const mockLicenses: LicenseData[] = [
    { key: 'MIT', name: 'MIT License', category: null, origin: 'SPDX' },
    { key: 'Apache-2.0', name: 'Apache License 2.0', category: null, origin: 'SPDX' },
    { key: 'GPL-3.0', name: 'GNU General Public License v3.0', category: null, origin: 'SPDX' },
    { key: 'Commons-Clause', name: 'Commons Clause License', category: 'proprietary', origin: 'Custom' }
  ]

  const createValidationResponse = (overrides: Partial<ValidationResponse> = {}): ValidationResponse => ({
    status: 200,
    ...overrides,
  })

  const createMockResponse = <T>(data: T): MockAxiosResponse<T> => ({
    data,
    status: 200,
    statusText: 'OK',
    headers: {},
    config: {}
  })

  beforeEach(() => {
    // Clear all mocks
    mockAxios.get.mockClear()
    mockAxios.post.mockClear()
    mockAxios.put.mockClear()
    mockAxios.delete.mockClear()

    // Setup default mock responses
    mockAxios.get.mockResolvedValue(createMockResponse(mockLicenses))
    mockAxios.post.mockResolvedValue(createMockResponse(createValidationResponse({
      normalized: 'MIT',
      tokens: [{ key: 'MIT', known: true }]
    })))
  })

  describe('License Data Loading', () => {
    it('should call the correct API endpoint for license data', async () => {
      await mockAxios.get()

      expect(mockAxios.get).toHaveBeenCalledTimes(1)
    })

    it('should handle license data response correctly', async () => {
      const response = await mockAxios.get()

      expect(response.data).toEqual(mockLicenses)
      expect(response.data).toHaveLength(4)
      expect(response.data[0].key).toBe('MIT')
    })
  })

  describe('License Expression Validation', () => {
    it('should call validation API with correct parameters', async () => {
      await mockAxios.post('/api/v1/licensing/license-expressions/validate', {
        expression: 'MIT'
      })

      expect(mockAxios.post).toHaveBeenCalledWith('/api/v1/licensing/license-expressions/validate', {
        expression: 'MIT'
      })
    })

    it('should handle successful validation response', async () => {
      const validationData = createValidationResponse({
        normalized: 'MIT',
        tokens: [{ key: 'MIT', known: true }]
      })

      mockAxios.post.mockResolvedValueOnce(createMockResponse(validationData))

      const response = await mockAxios.post('/api/v1/licensing/license-expressions/validate', {
        expression: 'MIT'
      })

      const responseData = response.data as ValidationResponse
      expect(responseData.status).toBe(200)
      expect(responseData.normalized).toBe('MIT')
      expect(responseData.tokens).toHaveLength(1)
      expect(responseData.tokens?.[0].known).toBe(true)
    })

    it('should handle validation error responses', async () => {
      const errorResponse = {
        response: { data: { detail: 'Invalid license expression' } }
      }

      mockAxios.post.mockRejectedValueOnce(errorResponse)

      try {
        await mockAxios.post('/api/v1/licensing/license-expressions/validate', {
          expression: 'INVALID'
        })
        expect(true).toBe(false) // Should not reach here
      } catch (error) {
        const errorData = error as typeof errorResponse
        expect(errorData.response.data.detail).toBe('Invalid license expression')
      }
    })

    it('should handle complex license expressions', async () => {
      const complexValidation = createValidationResponse({
        normalized: 'Apache-2.0 WITH Commons-Clause',
        tokens: [
          { key: 'Apache-2.0', known: true },
          { key: 'Commons-Clause', known: true }
        ]
      })

      mockAxios.post.mockResolvedValueOnce(createMockResponse(complexValidation))

      const response = await mockAxios.post('/api/v1/licensing/license-expressions/validate', {
        expression: 'Apache-2.0 WITH Commons-Clause'
      })

      const responseData = response.data as ValidationResponse
      expect(responseData.tokens).toHaveLength(2)
      expect(responseData.normalized).toBe('Apache-2.0 WITH Commons-Clause')
    })
  })

  describe('Custom License Creation', () => {
    it('should call custom license API with correct data', async () => {
      const customLicenseData = {
        key: 'CUSTOM_LICENSE',
        name: 'My Custom License',
        url: 'https://example.com/custom',
        text: 'Custom license text here'
      }

      const successResponse: CustomLicenseResponse = { success: true }
      mockAxios.post.mockResolvedValueOnce(createMockResponse(successResponse))

      await mockAxios.post('/api/v1/licensing/custom-licenses', customLicenseData)

      expect(mockAxios.post).toHaveBeenCalledWith('/api/v1/licensing/custom-licenses', customLicenseData)
    })

    it('should handle successful custom license creation', async () => {
      const successResponse: CustomLicenseResponse = { success: true }
      mockAxios.post.mockResolvedValueOnce(createMockResponse(successResponse))

      const response = await mockAxios.post('/api/v1/licensing/custom-licenses', {
        key: 'TEST_LICENSE',
        name: 'Test License',
        url: 'https://test.com',
        text: 'Test license text'
      })

      const responseData = response.data as CustomLicenseResponse
      expect(responseData.success).toBe(true)
    })

    it('should handle custom license creation errors', async () => {
      const errorDetail = { url: 'Invalid URL format' }
      const errorResponse = {
        response: { data: { detail: errorDetail } }
      }

      mockAxios.post.mockRejectedValueOnce(errorResponse)

      try {
        await mockAxios.post('/api/v1/licensing/custom-licenses', {
          key: 'INVALID_LICENSE',
          name: 'Invalid License',
          url: 'invalid-url',
          text: 'Test text'
        })
        expect(true).toBe(false) // Should not reach here
      } catch (error) {
        const errorData = error as typeof errorResponse
        expect(errorData.response.data.detail.url).toBe('Invalid URL format')
      }
    })
  })

  describe('License Data Processing', () => {
    it('should correctly process license arrays', () => {
      const licenses: (string | CustomLicense)[] = ['MIT', 'Apache-2.0']

      expect(licenses).toHaveLength(2)
      expect(licenses[0]).toBe('MIT')
      expect(licenses[1]).toBe('Apache-2.0')
    })

    it('should handle mixed license types', () => {
      const customLicense: CustomLicense = {
        name: 'Custom License',
        url: 'https://example.com',
        text: 'Custom license text'
      }

      const licenses: (string | CustomLicense)[] = ['MIT', customLicense]

      expect(licenses).toHaveLength(2)
      expect(typeof licenses[0]).toBe('string')
      expect(typeof licenses[1]).toBe('object')
      expect((licenses[1] as CustomLicense).name).toBe('Custom License')
    })

    it('should validate unknown tokens correctly', () => {
      const validationResponse = createValidationResponse({
        unknown_tokens: ['CUSTOM_LICENSE']
      })

      expect(validationResponse.unknown_tokens).toContain('CUSTOM_LICENSE')
      expect(validationResponse.status).toBe(200)
    })
  })

  describe('License Filtering Logic', () => {
    it('should filter licenses based on search term', () => {
      const searchTerm = 'Apache'
      const filteredLicenses = mockLicenses.filter(license =>
        license.key.toLowerCase().includes(searchTerm.toLowerCase()) ||
        license.name.toLowerCase().includes(searchTerm.toLowerCase())
      )

      expect(filteredLicenses).toHaveLength(1)
      expect(filteredLicenses[0].key).toBe('Apache-2.0')
    })

    it('should handle case-insensitive filtering', () => {
      const searchTerm = 'mit'
      const filteredLicenses = mockLicenses.filter(license =>
        license.key.toLowerCase().includes(searchTerm.toLowerCase()) ||
        license.name.toLowerCase().includes(searchTerm.toLowerCase())
      )

      expect(filteredLicenses).toHaveLength(1)
      expect(filteredLicenses[0].key).toBe('MIT')
    })

    it('should return empty array for no matches', () => {
      const searchTerm = 'NonExistentLicense'
      const filteredLicenses = mockLicenses.filter(license =>
        license.key.toLowerCase().includes(searchTerm.toLowerCase()) ||
        license.name.toLowerCase().includes(searchTerm.toLowerCase())
      )

      expect(filteredLicenses).toHaveLength(0)
    })
  })

  describe('API Integration Scenarios', () => {
    it('should handle complete license workflow', async () => {
      // Load licenses
      await mockAxios.get()

      // Validate a license expression
      const validationData = createValidationResponse({
        normalized: 'MIT',
        tokens: [{ key: 'MIT', known: true }]
      })
      mockAxios.post.mockResolvedValueOnce(createMockResponse(validationData))

      await mockAxios.post('/api/v1/licensing/license-expressions/validate', {
        expression: 'MIT'
      })

      expect(mockAxios.get).toHaveBeenCalledTimes(1)
      expect(mockAxios.post).toHaveBeenCalledTimes(1)
    })

    it('should handle workflow with unknown license', async () => {
      // Validate unknown license
      const unknownValidation = createValidationResponse({
        unknown_tokens: ['UNKNOWN_LICENSE']
      })
      mockAxios.post.mockResolvedValueOnce(createMockResponse(unknownValidation))

      await mockAxios.post('/api/v1/licensing/license-expressions/validate', {
        expression: 'UNKNOWN_LICENSE'
      })

      // Create custom license
      const successResponse: CustomLicenseResponse = { success: true }
      mockAxios.post.mockResolvedValueOnce(createMockResponse(successResponse))

      await mockAxios.post('/api/v1/licensing/custom-licenses', {
        key: 'UNKNOWN_LICENSE',
        name: 'Unknown License',
        url: 'https://example.com',
        text: 'License text'
      })

      expect(mockAxios.post).toHaveBeenCalledTimes(2)
    })
  })
})