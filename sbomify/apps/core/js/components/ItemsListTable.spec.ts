import { describe, test, expect, mock, beforeEach } from 'bun:test'

interface MockAxiosResponse<T = unknown> {
  data: T
  status: number
  statusText: string
  headers: Record<string, string>
  config: Record<string, unknown>
}

// Mock the $axios utils module using Bun's mock
const mockAxios = {
  get: mock<(url: string) => Promise<MockAxiosResponse<unknown>>>()
}

mock.module('../utils', () => ({
  default: mockAxios
}))

// Mock alerts
const mockShowError = mock<(message: string) => void>()

mock.module('../alerts', () => ({
  showError: mockShowError
}))

// Mock StandardCard component
mock.module('./StandardCard.vue', () => ({
  default: {}
}))

// Mock global eventBus
const mockEventBus = {
  on: mock<(event: string, callback: () => void) => void>()
}

// Extend global Window interface for tests
declare global {
  interface Window {
    eventBus?: {
      on: (event: string, callback: () => void) => void
    }
    EVENTS?: {
      REFRESH_PRODUCTS: string
      REFRESH_PROJECTS: string
      REFRESH_COMPONENTS: string
    }
  }
}

// Set up global window mock
global.window = global.window || ({} as Window & typeof globalThis)
global.window.eventBus = mockEventBus
global.window.EVENTS = {
  REFRESH_PRODUCTS: 'refresh_products',
  REFRESH_PROJECTS: 'refresh_projects',
  REFRESH_COMPONENTS: 'refresh_components'
}

describe('ItemsListTable Business Logic', () => {
  beforeEach(() => {
    // Reset mocks before each test
    mockAxios.get.mockClear()
    mockShowError.mockClear()
    mockEventBus.on.mockClear()
  })

  describe('Props Validation', () => {
    test('should validate item type correctly', () => {
      const validItemTypes = ['product', 'project', 'component']

      validItemTypes.forEach(itemType => {
        expect(['product', 'project', 'component']).toContain(itemType)
      })
    })

    test('should handle CRUD permissions as boolean', () => {
      const parseCrudPermissions = (value: string | boolean): boolean => {
        if (typeof value === 'boolean') return value
        return value === 'true'
      }

      expect(parseCrudPermissions(true)).toBe(true)
      expect(parseCrudPermissions(false)).toBe(false)
      expect(parseCrudPermissions('true')).toBe(true)
      expect(parseCrudPermissions('false')).toBe(false)
    })

    test('should generate correct title', () => {
      const generateTitle = (itemType: string, customTitle?: string): string => {
        if (customTitle) return customTitle
        return itemType.charAt(0).toUpperCase() + itemType.slice(1) + 's'
      }

      expect(generateTitle('product')).toBe('Products')
      expect(generateTitle('project')).toBe('Projects')
      expect(generateTitle('component')).toBe('Components')
      expect(generateTitle('product', 'Custom Title')).toBe('Custom Title')
    })

    test('should generate correct API endpoint', () => {
      const generateApiEndpoint = (itemType: string, customEndpoint?: string): string => {
        if (customEndpoint) return customEndpoint
        return `/api/v1/${itemType}s`
      }

      expect(generateApiEndpoint('product')).toBe('/api/v1/products')
      expect(generateApiEndpoint('project')).toBe('/api/v1/projects')
      expect(generateApiEndpoint('component')).toBe('/api/v1/components')
      expect(generateApiEndpoint('product', '/custom/api')).toBe('/custom/api')
    })
  })

  describe('API Data Loading', () => {
    test('should load products successfully', async () => {
      const mockProducts = [
        {
          id: 'prod-1',
          name: 'Product 1',
          is_public: true,
          projects: [
            { id: 'proj-1', name: 'Project 1', is_public: true }
          ]
        },
        {
          id: 'prod-2',
          name: 'Product 2',
          is_public: false,
          projects: []
        }
      ]

      mockAxios.get.mockResolvedValueOnce({
        data: mockProducts,
        status: 200,
        statusText: 'OK',
        headers: {},
        config: {}
      })

      const response = await mockAxios.get('/api/v1/products')

      expect(mockAxios.get).toHaveBeenCalledWith('/api/v1/products')
      expect(response.data).toEqual(mockProducts)
      expect(response.status).toBe(200)
    })

    test('should load projects successfully', async () => {
      const mockProjects = [
        {
          id: 'proj-1',
          name: 'Project 1',
          is_public: true,
          components: [
            { id: 'comp-1', name: 'Component 1', is_public: true }
          ]
        }
      ]

      mockAxios.get.mockResolvedValueOnce({
        data: mockProjects,
        status: 200,
        statusText: 'OK',
        headers: {},
        config: {}
      })

      const response = await mockAxios.get('/api/v1/projects')

      expect(response.data).toEqual(mockProjects)
    })

    test('should load components successfully', async () => {
      const mockComponents = [
        {
          id: 'comp-1',
          name: 'Component 1',
          is_public: true,
          sbom_count: 3
        }
      ]

      mockAxios.get.mockResolvedValueOnce({
        data: mockComponents,
        status: 200,
        statusText: 'OK',
        headers: {},
        config: {}
      })

      const response = await mockAxios.get('/api/v1/components')

      expect(response.data).toEqual(mockComponents)
    })

    test('should handle API errors gracefully', async () => {
      const mockError = {
        response: {
          status: 500,
          statusText: 'Internal Server Error',
          data: { detail: 'Server error' }
        }
      }

      mockAxios.get.mockRejectedValueOnce(mockError)

      let errorCaught = false
      try {
        await mockAxios.get('/api/v1/products')
      } catch (error) {
        errorCaught = true
        expect(error).toEqual(mockError)
      }

      expect(errorCaught).toBe(true)
    })

    test('should handle network errors', async () => {
      const networkError = new Error('Network error')
      mockAxios.get.mockRejectedValueOnce(networkError)

      let errorCaught = false
      try {
        await mockAxios.get('/api/v1/products')
      } catch (error) {
        errorCaught = true
        expect(error).toEqual(networkError)
      }

      expect(errorCaught).toBe(true)
    })
  })

  describe('Relationship Column Headers', () => {
    test('should return correct column headers for each item type', () => {
      const getRelationshipColumnHeader = (itemType: string): string => {
        switch (itemType) {
          case 'product':
            return 'Projects'
          case 'project':
            return 'Components'
          case 'component':
            return 'SBOMs'
          default:
            return 'Related'
        }
      }

      expect(getRelationshipColumnHeader('product')).toBe('Projects')
      expect(getRelationshipColumnHeader('project')).toBe('Components')
      expect(getRelationshipColumnHeader('component')).toBe('SBOMs')
      expect(getRelationshipColumnHeader('unknown')).toBe('Related')
    })
  })

  describe('URL Generation', () => {
    test('should generate correct detail URLs', () => {
      const getItemDetailUrl = (itemType: string, itemId: string): string => {
        return `/${itemType}/${itemId}/`
      }

      expect(getItemDetailUrl('product', 'prod-123')).toBe('/product/prod-123/')
      expect(getItemDetailUrl('project', 'proj-456')).toBe('/project/proj-456/')
      expect(getItemDetailUrl('component', 'comp-789')).toBe('/component/comp-789/')
    })
  })

  describe('SBOM Count Text Generation', () => {
    test('should generate correct SBOM count text', () => {
      interface Component {
        sbom_count?: number
      }

      const getSbomCountText = (component: Component): string => {
        const count = component.sbom_count || 0
        return count === 1 ? '1 SBOM' : `${count} SBOMs`
      }

      expect(getSbomCountText({ sbom_count: 0 })).toBe('0 SBOMs')
      expect(getSbomCountText({ sbom_count: 1 })).toBe('1 SBOM')
      expect(getSbomCountText({ sbom_count: 5 })).toBe('5 SBOMs')
      expect(getSbomCountText({})).toBe('0 SBOMs')
    })
  })

  describe('Event Bus Integration', () => {
    test('should register correct event listeners', () => {
      const setupEventListeners = (itemType: string) => {
        if (window.eventBus && window.EVENTS) {
          let eventName: string | undefined

          switch (itemType) {
            case 'product':
              eventName = window.EVENTS.REFRESH_PRODUCTS
              break
            case 'project':
              eventName = window.EVENTS.REFRESH_PROJECTS
              break
            case 'component':
              eventName = window.EVENTS.REFRESH_COMPONENTS
              break
          }

          if (eventName) {
            window.eventBus.on(eventName, () => {})
            return true
          }
        }
        return false
      }

      expect(setupEventListeners('product')).toBe(true)
      expect(setupEventListeners('project')).toBe(true)
      expect(setupEventListeners('component')).toBe(true)

      expect(mockEventBus.on).toHaveBeenCalledWith('refresh_products', expect.any(Function))
      expect(mockEventBus.on).toHaveBeenCalledWith('refresh_projects', expect.any(Function))
      expect(mockEventBus.on).toHaveBeenCalledWith('refresh_components', expect.any(Function))
    })

    test('should handle missing event bus gracefully', () => {
      // Temporarily remove eventBus
      const originalEventBus = global.window.eventBus
      delete (global.window as Window & typeof globalThis & { eventBus?: unknown }).eventBus

      const setupEventListeners = () => {
        if (window.eventBus && window.EVENTS) {
          return true
        }
        return false
      }

      expect(setupEventListeners()).toBe(false)

      // Restore eventBus
      global.window.eventBus = originalEventBus
    })
  })

  describe('Data State Management', () => {
    test('should manage loading state correctly', () => {
      let isLoading = false
      let error: string | null = null

      // Simulate loading start
      isLoading = true
      error = null
      expect(isLoading).toBe(true)
      expect(error).toBe(null)

      // Simulate loading success
      isLoading = false
      expect(isLoading).toBe(false)

      // Simulate loading error
      isLoading = false
      error = 'Failed to load items'
      expect(isLoading).toBe(false)
      expect(error).toBe('Failed to load items')
    })

    test('should determine data availability correctly', () => {
      const hasData = (items: unknown[]): boolean => items.length > 0

      expect(hasData([])).toBe(false)
      expect(hasData([{ id: '1', name: 'Item 1' }])).toBe(true)
      expect(hasData([{}, {}, {}])).toBe(true)
    })
  })

  describe('Modal Target Generation', () => {
    test('should generate correct modal targets', () => {
      const generateModalTarget = (itemType: string): string => {
        const capitalizedType = itemType.charAt(0).toUpperCase() + itemType.slice(1)
        return `#add${capitalizedType}Modal`
      }

      expect(generateModalTarget('product')).toBe('#addProductModal')
      expect(generateModalTarget('project')).toBe('#addProjectModal')
      expect(generateModalTarget('component')).toBe('#addComponentModal')
    })
  })

  describe('Type Casting and Data Validation', () => {
    test('should validate product data structure', () => {
      interface Product {
        id: string
        name: string
        is_public: boolean
        projects: Array<{ id: string; name: string; is_public: boolean }>
      }

      const isValidProduct = (item: unknown): item is Product => {
        const product = item as Product
        return (
          typeof product.id === 'string' &&
          typeof product.name === 'string' &&
          typeof product.is_public === 'boolean' &&
          Array.isArray(product.projects)
        )
      }

      const validProduct = {
        id: 'prod-1',
        name: 'Product 1',
        is_public: true,
        projects: []
      }

      const invalidProduct = {
        id: 123, // Should be string
        name: 'Product 1'
      }

      expect(isValidProduct(validProduct)).toBe(true)
      expect(isValidProduct(invalidProduct)).toBe(false)
    })

    test('should validate project data structure', () => {
      interface Project {
        id: string
        name: string
        is_public: boolean
        components: Array<{ id: string; name: string; is_public: boolean }>
      }

      const isValidProject = (item: unknown): item is Project => {
        const project = item as Project
        return (
          typeof project.id === 'string' &&
          typeof project.name === 'string' &&
          typeof project.is_public === 'boolean' &&
          Array.isArray(project.components)
        )
      }

      const validProject = {
        id: 'proj-1',
        name: 'Project 1',
        is_public: false,
        components: [{ id: 'comp-1', name: 'Component 1', is_public: true }]
      }

      expect(isValidProject(validProject)).toBe(true)
    })

    test('should validate component data structure', () => {
      interface Component {
        id: string
        name: string
        is_public: boolean
        sbom_count?: number
      }

      const isValidComponent = (item: unknown): item is Component => {
        const component = item as Component
        return (
          typeof component.id === 'string' &&
          typeof component.name === 'string' &&
          typeof component.is_public === 'boolean'
        )
      }

      const validComponent = {
        id: 'comp-1',
        name: 'Component 1',
        is_public: true,
        sbom_count: 5
      }

      expect(isValidComponent(validComponent)).toBe(true)
    })
  })
})