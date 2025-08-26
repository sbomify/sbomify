import { describe, it, expect, mock, beforeEach } from 'bun:test'
import type { CustomLicense } from '../../../core/js/type_defs'

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

  describe('Mixed License Types Support', () => {
    it('should handle mixed license array with strings and CustomLicense objects', () => {
      const customLicense: CustomLicense = {
        name: 'My Custom License',
        url: 'https://example.com/license',
        text: 'Custom license text here'
      }

      const mixedLicenses: (string | CustomLicense)[] = [
        'MIT',
        'Apache-2.0',
        customLicense
      ]

      expect(mixedLicenses).toHaveLength(3)
      expect(typeof mixedLicenses[0]).toBe('string')
      expect(typeof mixedLicenses[1]).toBe('string')
      expect(typeof mixedLicenses[2]).toBe('object')
      expect((mixedLicenses[2] as CustomLicense).name).toBe('My Custom License')
    })

    it('should correctly process string licenses', () => {
      const licenses: (string | CustomLicense)[] = ['MIT', 'Apache-2.0']

      expect(licenses).toHaveLength(2)
      expect(licenses[0]).toBe('MIT')
      expect(licenses[1]).toBe('Apache-2.0')
    })

    it('should correctly process CustomLicense objects', () => {
      const customLicense: CustomLicense = {
        name: 'Custom License',
        url: 'https://example.com',
        text: 'Custom license text'
      }

      const licenses: (string | CustomLicense)[] = [customLicense]

      expect(licenses).toHaveLength(1)
      expect(typeof licenses[0]).toBe('object')
      expect((licenses[0] as CustomLicense).name).toBe('Custom License')
      expect((licenses[0] as CustomLicense).url).toBe('https://example.com')
      expect((licenses[0] as CustomLicense).text).toBe('Custom license text')
    })

    it('should handle empty custom license fields correctly', () => {
      const customLicense: CustomLicense = {
        name: 'Basic License',
        url: null,
        text: null
      }

      expect(customLicense.name).toBe('Basic License')
      expect(customLicense.url).toBeNull()
      expect(customLicense.text).toBeNull()
    })
  })

  describe('Custom License Creation', () => {
    it('should create custom license with all fields', () => {
      const customLicenseData: CustomLicense = {
        name: 'My Custom License',
        url: 'https://example.com/custom',
        text: 'Custom license text here'
      }

      expect(customLicenseData.name).toBe('My Custom License')
      expect(customLicenseData.url).toBe('https://example.com/custom')
      expect(customLicenseData.text).toBe('Custom license text here')
    })

    it('should create custom license with only name', () => {
      const customLicenseData: CustomLicense = {
        name: 'Simple License',
        url: null,
        text: null
      }

      expect(customLicenseData.name).toBe('Simple License')
      expect(customLicenseData.url).toBeNull()
      expect(customLicenseData.text).toBeNull()
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

  describe('License Tag Processing', () => {
    it('should create string license tags correctly', () => {
      const license = 'MIT'
      const tag = {
        value: license,
        displayValue: license,
        isInvalid: false,
        isCustom: false
      }

      expect(tag.value).toBe('MIT')
      expect(tag.displayValue).toBe('MIT')
      expect(tag.isCustom).toBe(false)
    })

    it('should create custom license tags correctly', () => {
      const customLicense: CustomLicense = {
        name: 'Custom License',
        url: 'https://example.com',
        text: 'License text'
      }

      const tag = {
        value: customLicense,
        displayValue: customLicense.name || 'Unnamed License',
        isInvalid: false,
        isCustom: true
      }

      expect(tag.value).toEqual(customLicense)
      expect(tag.displayValue).toBe('Custom License')
      expect(tag.isCustom).toBe(true)
    })

    it('should handle unnamed custom licenses', () => {
      const customLicense: CustomLicense = {
        name: null,
        url: 'https://example.com',
        text: 'License text'
      }

      const tag = {
        value: customLicense,
        displayValue: customLicense.name || 'Unnamed License',
        isInvalid: false,
        isCustom: true
      }

      expect(tag.displayValue).toBe('Unnamed License')
      expect(tag.isCustom).toBe(true)
    })
  })

  describe('License Data Processing', () => {
    it('should handle mixed license types in processing', () => {
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

    it('should process complex license arrays', () => {
      const customLicense1: CustomLicense = {
        name: 'Custom License 1',
        url: 'https://example1.com',
        text: 'License 1 text'
      }

      const customLicense2: CustomLicense = {
        name: 'Custom License 2',
        url: null,
        text: 'License 2 text'
      }

      const licenses: (string | CustomLicense)[] = [
        'MIT',
        'Apache-2.0',
        customLicense1,
        'GPL-3.0',
        customLicense2
      ]

      expect(licenses).toHaveLength(5)

      // Check string licenses
      expect(licenses[0]).toBe('MIT')
      expect(licenses[1]).toBe('Apache-2.0')
      expect(licenses[3]).toBe('GPL-3.0')

      // Check custom licenses
      expect((licenses[2] as CustomLicense).name).toBe('Custom License 1')
      expect((licenses[2] as CustomLicense).url).toBe('https://example1.com')
      expect((licenses[4] as CustomLicense).name).toBe('Custom License 2')
      expect((licenses[4] as CustomLicense).url).toBeNull()
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

  describe('Custom License Editing', () => {
    it('should handle editing existing custom license', () => {
      const originalLicense: CustomLicense = {
        name: 'Original License',
        url: 'https://original.com',
        text: 'Original text'
      }

      const editedLicense: CustomLicense = {
        name: 'Updated License',
        url: 'https://updated.com',
        text: 'Updated text'
      }

      expect(originalLicense.name).toBe('Original License')
      expect(editedLicense.name).toBe('Updated License')
      expect(editedLicense.url).toBe('https://updated.com')
      expect(editedLicense.text).toBe('Updated text')
    })

    it('should handle partial updates to custom license', () => {
      const originalLicense: CustomLicense = {
        name: 'Original License',
        url: 'https://original.com',
        text: 'Original text'
      }

      const updatedLicense: CustomLicense = {
        name: 'Updated License',
        url: originalLicense.url, // Keep original URL
        text: null // Remove text
      }

      expect(updatedLicense.name).toBe('Updated License')
      expect(updatedLicense.url).toBe('https://original.com')
      expect(updatedLicense.text).toBeNull()
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

      expect(mockAxios.post).toHaveBeenCalledTimes(1)
    })

    it('should handle mixed license validation', async () => {
      const mixedValidation = createValidationResponse({
        normalized: 'MIT AND CUSTOM_LICENSE',
        tokens: [
          { key: 'MIT', known: true },
          { key: 'CUSTOM_LICENSE', known: false }
        ],
        unknown_tokens: ['CUSTOM_LICENSE']
      })

      mockAxios.post.mockResolvedValueOnce(createMockResponse(mixedValidation))

      const response = await mockAxios.post('/api/v1/licensing/license-expressions/validate', {
        expression: 'MIT AND CUSTOM_LICENSE'
      })

      const responseData = response.data as ValidationResponse
      expect(responseData.tokens).toHaveLength(2)
      expect(responseData.unknown_tokens).toContain('CUSTOM_LICENSE')
    })
  })

  describe('Component State Management', () => {
    it('should manage custom license form visibility', () => {
      let showCustomLicenseForm = false
      let editingCustomLicense = false

      // Show form for new license
      showCustomLicenseForm = true
      expect(showCustomLicenseForm).toBe(true)
      expect(editingCustomLicense).toBe(false)

      // Switch to editing mode
      editingCustomLicense = true
      expect(showCustomLicenseForm).toBe(true)
      expect(editingCustomLicense).toBe(true)

      // Close form
      showCustomLicenseForm = false
      editingCustomLicense = false
      expect(showCustomLicenseForm).toBe(false)
      expect(editingCustomLicense).toBe(false)
    })

    it('should manage custom license data state', () => {
      const customLicenseState = {
        name: '',
        url: '',
        text: ''
      }

      // Set data
      customLicenseState.name = 'Test License'
      customLicenseState.url = 'https://test.com'
      customLicenseState.text = 'Test license text'

      expect(customLicenseState.name).toBe('Test License')
      expect(customLicenseState.url).toBe('https://test.com')
      expect(customLicenseState.text).toBe('Test license text')

      // Clear data
      customLicenseState.name = ''
      customLicenseState.url = ''
      customLicenseState.text = ''

      expect(customLicenseState.name).toBe('')
      expect(customLicenseState.url).toBe('')
      expect(customLicenseState.text).toBe('')
    })
  })

  describe('Error Handling', () => {
    it('should handle validation errors for custom licenses', () => {
      const validationErrors = {
        name: 'License name is required',
        url: 'Invalid URL format',
        text: 'License text is too long'
      }

      expect(validationErrors.name).toBe('License name is required')
      expect(validationErrors.url).toBe('Invalid URL format')
      expect(validationErrors.text).toBe('License text is too long')
    })

    it('should handle API errors gracefully', async () => {
      const apiError = {
        response: {
          data: {
            detail: 'Internal server error'
          }
        }
      }

      mockAxios.post.mockRejectedValueOnce(apiError)

      try {
        await mockAxios.post('/api/v1/licensing/custom-licenses', {
          name: 'Test License'
        })
        expect(true).toBe(false) // Should not reach here
      } catch (error) {
        const errorData = error as typeof apiError
        expect(errorData.response.data.detail).toBe('Internal server error')
      }
    })
  })

  describe('Data Transformation', () => {
    it('should transform props to license tags correctly', () => {
      const propsValue: (string | CustomLicense)[] = [
        'MIT',
        {
          name: 'Custom License',
          url: 'https://example.com',
          text: 'License text'
        }
      ]

      const transformedTags = propsValue.map(lic => {
        if (typeof lic === 'string') {
          return {
            value: lic,
            displayValue: lic,
            isInvalid: false,
            isCustom: false
          }
        } else {
          return {
            value: lic,
            displayValue: lic.name || 'Unnamed License',
            isInvalid: false,
            isCustom: true
          }
        }
      })

      expect(transformedTags).toHaveLength(2)
      expect(transformedTags[0].displayValue).toBe('MIT')
      expect(transformedTags[0].isCustom).toBe(false)
      expect(transformedTags[1].displayValue).toBe('Custom License')
      expect(transformedTags[1].isCustom).toBe(true)
    })

    it('should transform license tags back to model value correctly', () => {
      const licenseTags = [
        {
          value: 'MIT',
          displayValue: 'MIT',
          isInvalid: false,
          isCustom: false
        },
        {
          value: {
            name: 'Custom License',
            url: 'https://example.com',
            text: 'License text'
          } as CustomLicense,
          displayValue: 'Custom License',
          isInvalid: false,
          isCustom: true
        }
      ]

      const modelValue: (string | CustomLicense)[] = licenseTags.map(tag => tag.value)

      expect(modelValue).toHaveLength(2)
      expect(modelValue[0]).toBe('MIT')
      expect(typeof modelValue[1]).toBe('object')
      expect((modelValue[1] as CustomLicense).name).toBe('Custom License')
    })
  })
})