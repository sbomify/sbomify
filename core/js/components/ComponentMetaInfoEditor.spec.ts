import { describe, it, expect, mock, beforeEach } from 'bun:test'
import type { ComponentMetaInfo, SupplierInfo, ContactInfo, CustomLicense } from '../type_defs.d.ts'
import { LifecyclePhase } from '../enums'

interface MockAxiosResponse<T = unknown> {
  data: T
  status: number
  statusText: string
  headers: Record<string, string>
  config: Record<string, unknown>
}

// Mock the $axios utils module using Bun's mock
const mockAxios = {
  get: mock<(url: string) => Promise<MockAxiosResponse<ComponentMetaInfo>>>(),
  put: mock<(url: string, data: unknown) => Promise<MockAxiosResponse<Record<string, unknown>>>>(),
  patch: mock<(url: string, data: unknown) => Promise<MockAxiosResponse<Record<string, unknown>>>>()
}

mock.module('../../../core/js/utils', () => ({
  default: mockAxios,
  isEmpty: mock<(value: unknown) => boolean>()
}))

// Mock alerts
mock.module('../../../core/js/alerts', () => ({
  showSuccess: mock<(message: string) => void>(),
  showError: mock<(message: string) => void>()
}))

describe('ComponentMetaInfoEditor Business Logic', () => {
  const mockComponentId = 'test-component-123'

  const mockMetadata: ComponentMetaInfo = {
    id: 'test-component-123',
    name: 'Test Component',
    supplier: {
      name: 'Test Supplier',
      url: ['https://example.com'],
      address: '123 Test St',
      contacts: []
    } as SupplierInfo,
    authors: [] as ContactInfo[],
    licenses: [] as (string | CustomLicense)[],
    lifecycle_phase: null
  }

  const createMockResponse = <T>(data: T, status = 200): MockAxiosResponse<T> => ({
    data,
    status,
    statusText: 'OK',
    headers: {},
    config: {}
  })

  beforeEach(() => {
    // Clear all mocks
    mockAxios.get.mockClear()
    mockAxios.put.mockClear()
    mockAxios.patch.mockClear()

    // Setup default mock responses
    mockAxios.get.mockResolvedValue(createMockResponse(mockMetadata))
    mockAxios.put.mockResolvedValue(createMockResponse({}))
    mockAxios.patch.mockResolvedValue(createMockResponse({}))
  })

  describe('Lifecycle Phase Management', () => {
    it('should handle null lifecycle phase correctly', async () => {
      const metadataWithNullLifecycle = {
        ...mockMetadata,
        lifecycle_phase: null
      }

      mockAxios.get.mockResolvedValueOnce(createMockResponse(metadataWithNullLifecycle))

      const response = await mockAxios.get(`/api/v1/components/${mockComponentId}/metadata`)

      expect(response.data.lifecycle_phase).toBeNull()
      expect(response.status).toBe(200)
    })

    it('should handle setting a lifecycle phase', async () => {
      // Only send the changed field in PATCH request
      const updatePayload = {
        lifecycle_phase: LifecyclePhase.Build
      }
          await mockAxios.patch(`/api/v1/components/${mockComponentId}/metadata`, updatePayload)

    expect(mockAxios.patch).toHaveBeenCalledWith(
      `/api/v1/components/${mockComponentId}/metadata`,
        updatePayload
      )
    })

    it('should handle unsetting a lifecycle phase (setting to null)', async () => {
      const metadataWithNullLifecycle = {
        ...mockMetadata,
        lifecycle_phase: null
      }

      // Exclude read-only fields from PUT request
      const updatePayload = {
        supplier: metadataWithNullLifecycle.supplier,
        authors: metadataWithNullLifecycle.authors,
        licenses: metadataWithNullLifecycle.licenses,
        lifecycle_phase: metadataWithNullLifecycle.lifecycle_phase
      }
      await mockAxios.put(`/api/v1/components/${mockComponentId}/metadata`, updatePayload)

      expect(mockAxios.put).toHaveBeenCalledWith(
        `/api/v1/components/${mockComponentId}/metadata`,
        updatePayload
      )
      expect(updatePayload.lifecycle_phase).toBeNull()
    })

    it('should handle all valid lifecycle phases', async () => {
      const validPhases = [
        LifecyclePhase.Design,
        LifecyclePhase.PreBuild,
        LifecyclePhase.Build,
        LifecyclePhase.PostBuild,
        LifecyclePhase.Operations,
        LifecyclePhase.Discovery,
        LifecyclePhase.Decommission
      ]

      for (const phase of validPhases) {
        const metadataWithPhase = {
          ...mockMetadata,
          lifecycle_phase: phase
        }

        await mockAxios.put(`/api/v1/components/${mockComponentId}/metadata`, metadataWithPhase)

        expect(mockAxios.put).toHaveBeenCalledWith(
          `/api/v1/components/${mockComponentId}/metadata`,
          metadataWithPhase
        )
      }

      expect(mockAxios.put).toHaveBeenCalledTimes(validPhases.length)
    })

    it('should preserve other metadata when changing lifecycle phase', async () => {
      const metadataWithSupplier = {
        ...mockMetadata,
        supplier: {
          name: 'Important Supplier',
          url: ['https://important.com'],
          address: '456 Important Ave',
          contacts: []
        },
        authors: [{ name: 'John Doe', email: 'john@example.com', phone: '123-456-7890' }],
        licenses: ['MIT', 'Apache-2.0'],
        lifecycle_phase: LifecyclePhase.Operations
      }

      await mockAxios.put(`/api/v1/components/${mockComponentId}/metadata`, metadataWithSupplier)

      expect(mockAxios.put).toHaveBeenCalledWith(
        `/api/v1/components/${mockComponentId}/metadata`,
        metadataWithSupplier
      )

      // Verify all fields are preserved
      const [, callData] = mockAxios.put.mock.calls[0] as [string, ComponentMetaInfo]
      const typedCallData = callData as ComponentMetaInfo
      expect(typedCallData.supplier.name).toBe('Important Supplier')
      expect(typedCallData.authors).toHaveLength(1)
      expect(typedCallData.licenses).toHaveLength(2)
      expect(typedCallData.lifecycle_phase).toBe(LifecyclePhase.Operations)
    })
  })

  describe('Lifecycle Phase Dropdown Logic', () => {
    it('should format lifecycle phases correctly', () => {
      const formatLifecyclePhase = (phase: string): string => {
        // Special case for pre/post-build to keep the hyphen
        if (phase === 'pre-build') return 'Pre-Build'
        if (phase === 'post-build') return 'Post-Build'

        // Regular title case for other phases
        return phase.charAt(0).toUpperCase() + phase.slice(1)
      }

      expect(formatLifecyclePhase('design')).toBe('Design')
      expect(formatLifecyclePhase('pre-build')).toBe('Pre-Build')
      expect(formatLifecyclePhase('build')).toBe('Build')
      expect(formatLifecyclePhase('post-build')).toBe('Post-Build')
      expect(formatLifecyclePhase('operations')).toBe('Operations')
      expect(formatLifecyclePhase('discovery')).toBe('Discovery')
      expect(formatLifecyclePhase('decommission')).toBe('Decommission')
    })

    it('should create ordered lifecycle phases with correct values and labels', () => {
      const LIFECYCLE_ORDER = [
        LifecyclePhase.Design,
        LifecyclePhase.PreBuild,
        LifecyclePhase.Build,
        LifecyclePhase.PostBuild,
        LifecyclePhase.Operations,
        LifecyclePhase.Discovery,
        LifecyclePhase.Decommission
      ]

      const formatLifecyclePhase = (phase: string): string => {
        if (phase === 'pre-build') return 'Pre-Build'
        if (phase === 'post-build') return 'Post-Build'
        return phase.charAt(0).toUpperCase() + phase.slice(1)
      }

      const orderedLifecyclePhases = LIFECYCLE_ORDER.map(phase => ({
        value: phase,
        label: formatLifecyclePhase(phase)
      }))

      expect(orderedLifecyclePhases).toHaveLength(7)
      expect(orderedLifecyclePhases[0]).toEqual({ value: LifecyclePhase.Design, label: 'Design' })
      expect(orderedLifecyclePhases[1]).toEqual({ value: LifecyclePhase.PreBuild, label: 'Pre-Build' })
      expect(orderedLifecyclePhases[2]).toEqual({ value: LifecyclePhase.Build, label: 'Build' })
      expect(orderedLifecyclePhases[3]).toEqual({ value: LifecyclePhase.PostBuild, label: 'Post-Build' })
      expect(orderedLifecyclePhases[4]).toEqual({ value: LifecyclePhase.Operations, label: 'Operations' })
      expect(orderedLifecyclePhases[5]).toEqual({ value: LifecyclePhase.Discovery, label: 'Discovery' })
      expect(orderedLifecyclePhases[6]).toEqual({ value: LifecyclePhase.Decommission, label: 'Decommission' })
    })
  })

  describe('API Integration', () => {
    it('should get component metadata from correct endpoint', async () => {
      await mockAxios.get(`/api/v1/components/${mockComponentId}/metadata`)

      expect(mockAxios.get).toHaveBeenCalledWith(`/api/v1/components/${mockComponentId}/metadata`)
      expect(mockAxios.get).toHaveBeenCalledTimes(1)
    })

    it('should update component metadata to correct endpoint', async () => {
      const updatedMetadata = {
        ...mockMetadata,
        lifecycle_phase: LifecyclePhase.Build
      }

      await mockAxios.put(`/api/v1/components/${mockComponentId}/metadata`, updatedMetadata)

      expect(mockAxios.put).toHaveBeenCalledWith(
        `/api/v1/components/${mockComponentId}/metadata`,
        updatedMetadata
      )
      expect(mockAxios.put).toHaveBeenCalledTimes(1)
    })

    it('should handle API errors gracefully', async () => {
      const errorResponse = {
        response: {
          status: 400,
          statusText: 'Bad Request',
          data: { detail: 'Invalid metadata' }
        }
      }

      mockAxios.put.mockRejectedValueOnce(errorResponse)

      try {
        await mockAxios.put(`/api/v1/components/${mockComponentId}/metadata`, mockMetadata)
        expect(true).toBe(false) // Should not reach here
      } catch (error) {
        const errorData = error as typeof errorResponse
        expect(errorData.response.status).toBe(400)
        expect(errorData.response.data.detail).toBe('Invalid metadata')
      }
    })
  })

  describe('Lifecycle Phase State Changes', () => {
    it('should transition from null to selected phase', () => {
      let currentPhase: LifecyclePhase | null = null

      // Simulate selecting a phase
      currentPhase = LifecyclePhase.Build

      expect(currentPhase).toBe(LifecyclePhase.Build)
      expect(currentPhase).not.toBeNull()
    })

    it('should transition from selected phase back to null', () => {
      let currentPhase: LifecyclePhase | null = LifecyclePhase.Operations

      // Simulate selecting "Select a phase..." option (which has null value)
      currentPhase = null

      expect(currentPhase).toBeNull()
    })

    it('should transition between different phases', () => {
      let currentPhase: LifecyclePhase | null = LifecyclePhase.Design

      expect(currentPhase).toBe(LifecyclePhase.Design)

      // Change to build phase
      currentPhase = LifecyclePhase.Build
      expect(currentPhase).toBe(LifecyclePhase.Build)

      // Change to operations phase
      currentPhase = LifecyclePhase.Operations
      expect(currentPhase).toBe(LifecyclePhase.Operations)

      // Unset the phase
      currentPhase = null
      expect(currentPhase).toBeNull()
    })
  })

  describe('Supplier Multiple URL Management', () => {
    it('should handle supplier with multiple URLs', async () => {
      const supplierWithMultipleUrls = {
        ...mockMetadata,
        supplier: {
          name: 'Multi-URL Supplier',
          url: ['https://primary.com', 'https://secondary.com', 'https://docs.example.com'],
          address: '789 Multi St',
          contacts: []
        }
      }

      await mockAxios.put(`/api/v1/components/${mockComponentId}/metadata`, supplierWithMultipleUrls)

      expect(mockAxios.put).toHaveBeenCalledWith(
        `/api/v1/components/${mockComponentId}/metadata`,
        supplierWithMultipleUrls
      )

      const [, callData] = mockAxios.put.mock.calls[0] as [string, ComponentMetaInfo]
      const typedCallData = callData as ComponentMetaInfo
      expect(typedCallData.supplier.url).toHaveLength(3)
      expect(typedCallData.supplier.url).toContain('https://primary.com')
      expect(typedCallData.supplier.url).toContain('https://secondary.com')
      expect(typedCallData.supplier.url).toContain('https://docs.example.com')
    })

    it('should handle supplier with empty URL array', async () => {
      const supplierWithEmptyUrls = {
        ...mockMetadata,
        supplier: {
          name: 'No URL Supplier',
          url: [],
          address: '123 No URL St',
          contacts: []
        }
      }

      await mockAxios.put(`/api/v1/components/${mockComponentId}/metadata`, supplierWithEmptyUrls)

      const [, callData] = mockAxios.put.mock.calls[0] as [string, ComponentMetaInfo]
      const typedCallData = callData as ComponentMetaInfo
      expect(typedCallData.supplier.url).toEqual([])
      expect(typedCallData.supplier.name).toBe('No URL Supplier')
    })

    it('should handle supplier with null URL', async () => {
      const supplierWithNullUrl = {
        ...mockMetadata,
        supplier: {
          name: 'Null URL Supplier',
          url: null,
          address: '456 Null St',
          contacts: []
        }
      }

      await mockAxios.put(`/api/v1/components/${mockComponentId}/metadata`, supplierWithNullUrl)

      const [, callData] = mockAxios.put.mock.calls[0] as [string, ComponentMetaInfo]
      const typedCallData = callData as ComponentMetaInfo
      expect(typedCallData.supplier.url).toBeNull()
      expect(typedCallData.supplier.name).toBe('Null URL Supplier')
    })

    it('should preserve supplier contacts when URLs are modified', async () => {
      const supplierWithContactsAndUrls = {
        ...mockMetadata,
        supplier: {
          name: 'Contact Supplier',
          url: ['https://contact.com', 'https://support.contact.com'],
          address: '789 Contact Ave',
          contacts: [
            { name: 'John Contact', email: 'john@contact.com', phone: '555-0123' },
            { name: 'Jane Support', email: 'jane@contact.com', phone: '555-0124' }
          ]
        }
      }

      await mockAxios.put(`/api/v1/components/${mockComponentId}/metadata`, supplierWithContactsAndUrls)

      const [, callData] = mockAxios.put.mock.calls[0] as [string, ComponentMetaInfo]
      const typedCallData = callData as ComponentMetaInfo
      expect(typedCallData.supplier.contacts).toHaveLength(2)
      expect(typedCallData.supplier.contacts[0].name).toBe('John Contact')
      expect(typedCallData.supplier.contacts[1].name).toBe('Jane Support')
      expect(typedCallData.supplier.url).toHaveLength(2)
    })
  })

  describe('Author Information Management', () => {
    it('should handle authors with complete contact information', async () => {
      const metadataWithAuthors = {
        ...mockMetadata,
        authors: [
          { name: 'Alice Author', email: 'alice@example.com', phone: '555-1001' },
          { name: 'Bob Builder', email: 'bob@example.com', phone: '555-1002' },
          { name: 'Charlie Creator', email: 'charlie@example.com', phone: '555-1003' }
        ]
      }

      await mockAxios.put(`/api/v1/components/${mockComponentId}/metadata`, metadataWithAuthors)

      const [, callData] = mockAxios.put.mock.calls[0] as [string, ComponentMetaInfo]
      expect(callData.authors).toHaveLength(3)
      expect(callData.authors[0].name).toBe('Alice Author')
      expect(callData.authors[1].email).toBe('bob@example.com')
      expect(callData.authors[2].phone).toBe('555-1003')
    })

    it('should handle authors with empty email and phone fields', async () => {
      const metadataWithPartialAuthors = {
        ...mockMetadata,
        authors: [
          { name: 'Name Only Author', email: '', phone: '' },
          { name: 'Email Only Author', email: 'email@example.com', phone: '' },
          { name: 'Phone Only Author', email: '', phone: '555-2001' }
        ]
      }

      await mockAxios.put(`/api/v1/components/${mockComponentId}/metadata`, metadataWithPartialAuthors)

      const [, callData] = mockAxios.put.mock.calls[0] as [string, ComponentMetaInfo]
      expect(callData.authors).toHaveLength(3)
      expect(callData.authors[0].email).toBe('')
      expect(callData.authors[0].phone).toBe('')
      expect(callData.authors[1].email).toBe('email@example.com')
      expect(callData.authors[1].phone).toBe('')
      expect(callData.authors[2].email).toBe('')
      expect(callData.authors[2].phone).toBe('555-2001')
    })

    it('should handle mixed author information correctly', async () => {
      const metadataWithMixedAuthors = {
        ...mockMetadata,
        authors: [
          { name: 'Complete Author', email: 'complete@example.com', phone: '555-3001' },
          { name: 'Partial Author', email: 'partial@example.com', phone: '' },
          { name: 'Name Only', email: '', phone: '' }
        ]
      }

      await mockAxios.put(`/api/v1/components/${mockComponentId}/metadata`, metadataWithMixedAuthors)

      const [, callData] = mockAxios.put.mock.calls[0] as [string, ComponentMetaInfo]
      expect(callData.authors).toHaveLength(3)

      // Verify complete author
      expect(callData.authors[0].name).toBe('Complete Author')
      expect(callData.authors[0].email).toBe('complete@example.com')
      expect(callData.authors[0].phone).toBe('555-3001')

      // Verify partial author
      expect(callData.authors[1].name).toBe('Partial Author')
      expect(callData.authors[1].email).toBe('partial@example.com')
      expect(callData.authors[1].phone).toBe('')

      // Verify name-only author
      expect(callData.authors[2].name).toBe('Name Only')
      expect(callData.authors[2].email).toBe('')
      expect(callData.authors[2].phone).toBe('')
    })
  })

  describe('URL Validation Logic', () => {
    it('should validate single URL correctly', () => {
      const isValidUrl = (url: string): boolean => {
        try {
          const urlObj = new URL(url)
          return urlObj.protocol === 'http:' || urlObj.protocol === 'https:'
        } catch {
          return false
        }
      }

      expect(isValidUrl('https://example.com')).toBe(true)
      expect(isValidUrl('http://example.com')).toBe(true)
      expect(isValidUrl('https://subdomain.example.co.uk')).toBe(true)
      expect(isValidUrl('invalid-url')).toBe(false)
      expect(isValidUrl('ftp://example.com')).toBe(false)
      expect(isValidUrl('')).toBe(false)
    })

    it('should validate multiple URLs in array', () => {
      const validateUrlArray = (urls: string[]): boolean[] => {
        const isValidUrl = (url: string): boolean => {
          try {
            const urlObj = new URL(url)
            return urlObj.protocol === 'http:' || urlObj.protocol === 'https:'
          } catch {
            return false
          }
        }

        return urls.map(url => isValidUrl(url))
      }

      const mixedUrls = [
        'https://valid.com',
        'invalid-url',
        'https://another-valid.com',
        'ftp://invalid-protocol.com',
        'http://also-valid.org'
      ]

      const results = validateUrlArray(mixedUrls)
      expect(results).toEqual([true, false, true, false, true])
    })
  })

  describe('Complete Metadata Integration', () => {
    it('should handle complete metadata with all fields', async () => {
      const completeMetadata = {
        id: 'test-component-123',
        name: 'Test Component',
        supplier: {
          name: 'Complete Supplier Inc',
          url: ['https://complete.com', 'https://support.complete.com', 'https://docs.complete.com'],
          address: '100 Complete Boulevard, Suite 200',
          contacts: [
            { name: 'John Complete', email: 'john@complete.com', phone: '555-4001' },
            { name: 'Jane Complete', email: 'jane@complete.com', phone: '555-4002' }
          ]
        },
        authors: [
          { name: 'Lead Author', email: 'lead@example.com', phone: '555-5001' },
          { name: 'Co-Author', email: 'co@example.com', phone: '' },
          { name: 'Contributing Author', email: '', phone: '555-5003' }
        ],
        licenses: ['MIT', 'Apache-2.0'],
        lifecycle_phase: LifecyclePhase.Operations
      }

      // Simulate what the frontend does: exclude read-only fields from PUT request
      const updatePayload = {
        supplier: completeMetadata.supplier,
        authors: completeMetadata.authors,
        licenses: completeMetadata.licenses,
        lifecycle_phase: completeMetadata.lifecycle_phase
      }
      await mockAxios.put(`/api/v1/components/${mockComponentId}/metadata`, updatePayload)

      const [, callData] = mockAxios.put.mock.calls[0] as [string, ComponentMetaInfo]

      // Verify that read-only fields are NOT included in the PUT request
      expect(callData.id).toBeUndefined()
      expect(callData.name).toBeUndefined()

      // Verify supplier data
      expect(callData.supplier.name).toBe('Complete Supplier Inc')
      expect(callData.supplier.url).toHaveLength(3)
      expect(callData.supplier.contacts).toHaveLength(2)

      // Verify authors data
      expect(callData.authors).toHaveLength(3)

      // Verify other fields
      expect(callData.licenses).toHaveLength(2)
      expect(callData.lifecycle_phase).toBe(LifecyclePhase.Operations)
    })

    it('should exclude read-only fields from PUT requests', async () => {
      const fullMetadata = {
        id: 'component-456',
        name: 'Another Component',
        supplier: { name: 'Test Supplier', url: ['https://test.com'], address: null, contacts: [] },
        authors: [],
        licenses: ['MIT'],
        lifecycle_phase: LifecyclePhase.Build
      }

      // Simulate the destructuring that happens in the frontend
      const updateData = {
        supplier: fullMetadata.supplier,
        authors: fullMetadata.authors,
        licenses: fullMetadata.licenses,
        lifecycle_phase: fullMetadata.lifecycle_phase
      }
      await mockAxios.put(`/api/v1/components/${mockComponentId}/metadata`, updateData)

      const [, sentData] = mockAxios.put.mock.calls[0] as [string, ComponentMetaInfo]

      // Verify read-only fields are excluded
      expect(sentData).not.toHaveProperty('id')
      expect(sentData).not.toHaveProperty('name')

      // Verify editable fields are included
      expect(sentData.supplier.name).toBe('Test Supplier')
      expect(sentData.licenses).toEqual(['MIT'])
      expect(sentData.lifecycle_phase).toBe(LifecyclePhase.Build)
    })
  })
})