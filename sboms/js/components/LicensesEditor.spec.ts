import { mount, VueWrapper } from '@vue/test-utils'
import LicensesEditor from './LicensesEditor.vue'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { nextTick } from 'vue'
import type { CustomLicense } from '../type_defs'

// Mock the $axios utils module
vi.mock('../../../core/js/utils', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn()
  },
  isEmpty: vi.fn()
}))

import $axios from '../../../core/js/utils'


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

interface MockAxiosResponse<T = unknown> {
  data: T
  status: number
  statusText: string
  headers: Record<string, string>
  config: Record<string, unknown>
}

describe('LicensesEditor.vue', () => {
  let wrapper: VueWrapper<InstanceType<typeof LicensesEditor>>

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

  const defaultProps = {
    modelValue: [] as (string | CustomLicense)[],
    validationResponse: createValidationResponse(),
  }

  beforeEach(async () => {
    vi.clearAllMocks()

    // Setup default mock responses
    vi.mocked($axios.get).mockResolvedValue(createMockResponse(mockLicenses))
    vi.mocked($axios.post).mockResolvedValue(createMockResponse({
      status: 200,
      normalized: 'MIT',
      tokens: [{ key: 'MIT', known: true }]
    }))
  })

  afterEach(() => {
    if (wrapper) {
      wrapper.unmount()
    }
  })

  describe('Component Initialization', () => {
    it('should render with default props', async () => {
      wrapper = mount(LicensesEditor, { props: defaultProps })

      expect(wrapper.find('input[type="text"]').exists()).toBe(true)
      expect(wrapper.find('.license-suggestions').exists()).toBe(false)
      expect(wrapper.find('.custom-license-form').exists()).toBe(false)
    })

    it('should initialize tags from modelValue prop', async () => {
      wrapper = mount(LicensesEditor, {
        props: {
          ...defaultProps,
          modelValue: ['MIT', 'Apache-2.0']
        }
      })

      await nextTick()
      await nextTick() // Wait for mounted hooks

      const input = wrapper.find('input[type="text"]')
      expect((input.element as HTMLInputElement).value).toBe('')

      // Should show tags instead
      const tags = wrapper.findAll('.license-tag')
      expect(tags).toHaveLength(2)
      expect(tags[0].text()).toContain('MIT')
      expect(tags[1].text()).toContain('Apache-2.0')
    })

    it('should handle custom license objects in modelValue', async () => {
      const customLicense: CustomLicense = {
        name: 'Custom License',
        url: 'https://example.com',
        text: 'Custom license text'
      }
      wrapper = mount(LicensesEditor, {
        props: {
          ...defaultProps,
          modelValue: ['MIT', customLicense]
        }
      })

      await nextTick()
      await nextTick()

      const input = wrapper.find('input[type="text"]')
      expect((input.element as HTMLInputElement).value).toBe('')

      // Should show tags instead
      const tags = wrapper.findAll('.license-tag')
      expect(tags).toHaveLength(2)
      expect(tags[0].text()).toContain('MIT')
      expect(tags[1].text()).toContain('Custom License')
    })

    it('should load licenses on mount', async () => {
      wrapper = mount(LicensesEditor, { props: defaultProps })
      await nextTick()

      expect($axios.get).toHaveBeenCalledWith('/api/v1/licensing/licenses')
    })
  })

  describe('License Expression Input', () => {
    beforeEach(async () => {
      wrapper = mount(LicensesEditor, { props: defaultProps })
      await nextTick()
    })

    it('should emit update:modelValue when Add button is clicked', async () => {
      vi.mocked($axios.post).mockResolvedValueOnce(createMockResponse({
        status: 200,
        normalized: 'MIT',
        tokens: [{ key: 'MIT', known: true }]
      }))

      const input = wrapper.find('input[type="text"]')
      const addButton = wrapper.find('.add-license-btn')

      await input.setValue('MIT')
      await addButton.trigger('click')
      await nextTick()

      expect(wrapper.emitted('update:modelValue')).toBeTruthy()
      const emittedEvents = wrapper.emitted('update:modelValue') as Array<Array<(string | CustomLicense)[]>>
      expect(emittedEvents[emittedEvents.length - 1][0]).toEqual(['MIT'])
    })

    it('should emit empty array when all tags are removed', async () => {
      // First add a license tag
      const input = wrapper.find('input[type="text"]')
      const addButton = wrapper.find('.add-license-btn')

      await input.setValue('MIT')
      await addButton.trigger('click')
      await nextTick()

      // Verify tag was added
      expect(wrapper.findAll('.license-tag')).toHaveLength(1)

      // Remove the tag using X button
      const removeButton = wrapper.find('.license-tag-remove')
      await removeButton.trigger('click')
      await nextTick()

      const emittedEvents = wrapper.emitted('update:modelValue') as Array<Array<(string | CustomLicense)[]>>
      expect(emittedEvents[emittedEvents.length - 1][0]).toEqual([])
    })

    it('should debounce validation API calls', async () => {
      const input = wrapper.find('input[type="text"]')

      await input.setValue('M')
      await input.setValue('MI')
      await input.setValue('MIT')

      // Should not call API immediately
      expect(vi.mocked($axios.post)).not.toHaveBeenCalled()

      // Wait for debounce
      await new Promise(resolve => setTimeout(resolve, 350))

      // Should only call API once after debounce
      expect(vi.mocked($axios.post)).toHaveBeenCalledTimes(1)
      expect(vi.mocked($axios.post)).toHaveBeenCalledWith('/api/v1/licensing/license-expressions/validate', {
        expression: 'MIT'
      })
    })

    it('should handle validation API errors gracefully', async () => {
      vi.mocked($axios.post).mockRejectedValueOnce(new Error('Network error'))

      const input = wrapper.find('input[type="text"]')
      const addButton = wrapper.find('.add-license-btn')

      await input.setValue('INVALID_LICENSE')
      await addButton.trigger('click')
      await nextTick()

      // Should emit the raw expression even on validation error
      const emittedEvents = wrapper.emitted('update:modelValue') as Array<Array<(string | CustomLicense)[]>>
      expect(emittedEvents[emittedEvents.length - 1][0]).toEqual(['INVALID_LICENSE'])
    })

    it('should show validation error when API returns error', async () => {
      const errorDetail = 'Invalid license expression format'
      vi.mocked($axios.post).mockRejectedValueOnce({
        response: { data: { detail: errorDetail } }
      })

      const input = wrapper.find('input[type="text"]')
      await input.setValue('INVALID')
      await new Promise(resolve => setTimeout(resolve, 350))
      await nextTick()

      expect(wrapper.find('.invalid-feedback').text()).toBe('Invalid license expression')
      expect(input.classes()).toContain('is-invalid')
    })
  })

  describe('Autocomplete Functionality', () => {
    beforeEach(async () => {
      wrapper = mount(LicensesEditor, { props: defaultProps })
      await nextTick()
      // Wait for licenses to load
      await new Promise(resolve => setTimeout(resolve, 100))
    })

    it('should show suggestions dropdown when typing', async () => {
      const input = wrapper.find('input[type="text"]')
      await input.trigger('focus')
      await input.setValue('MIT')
      await nextTick()

      // Check if suggestions appear in DOM
      expect(wrapper.find('.license-suggestions').exists()).toBe(true)
    })

    it('should filter suggestions based on input', async () => {
      const input = wrapper.find('input[type="text"]')
      await input.setValue('Apache')
      await input.trigger('focus')
      await nextTick()

      const suggestions = wrapper.findAll('.license-suggestion')
      const hasApacheSuggestion = suggestions.some(suggestion =>
        suggestion.text().includes('Apache-2.0')
      )
      expect(hasApacheSuggestion).toBe(true)
    })

    it('should handle keyboard navigation in suggestions', async () => {
      const input = wrapper.find('input[type="text"]')
      await input.setValue('Apache')
      await input.trigger('focus')
      await nextTick()

      // Simulate arrow down key
      await input.trigger('keydown', { key: 'ArrowDown' })
      await nextTick()

      // Check if first suggestion is highlighted
      const suggestions = wrapper.findAll('.license-suggestion')
      if (suggestions.length > 0) {
        expect(suggestions[0].classes()).toContain('active')
      }
    })

    it('should hide suggestions on escape', async () => {
      const input = wrapper.find('input[type="text"]')
      await input.setValue('MIT')
      await input.trigger('focus')
      await nextTick()

      // Ensure suggestions are visible
      expect(wrapper.find('.license-suggestions').exists()).toBe(true)

      await input.trigger('keydown', { key: 'Escape' })
      await nextTick()

      expect(wrapper.find('.license-suggestions').exists()).toBe(false)
    })

    it('should hide suggestions on blur with delay', async () => {
      const input = wrapper.find('input[type="text"]')
      await input.setValue('MIT')
      await input.trigger('focus')
      await nextTick()

      // Ensure suggestions are visible
      expect(wrapper.find('.license-suggestions').exists()).toBe(true)

      await input.trigger('blur')

      // Should be hidden after delay
      await new Promise(resolve => setTimeout(resolve, 250))
      await nextTick()
      expect(wrapper.find('.license-suggestions').exists()).toBe(false)
    })
  })

  describe('Custom License Form', () => {
    it('should show custom license form when unknown tokens exist', async () => {
      wrapper = mount(LicensesEditor, {
        props: {
          ...defaultProps,
          validationResponse: createValidationResponse({ unknown_tokens: ['CUSTOM_LICENSE'] })
        }
      })
      await nextTick()

      expect(wrapper.find('.custom-license-form').exists()).toBe(true)
      expect(wrapper.find('.alert-info').text()).toContain('CUSTOM_LICENSE')
    })

    it('should submit custom license form', async () => {
      // Mock the validation endpoint to not interfere
      vi.mocked($axios.post).mockImplementation((url) => {
        if (url === '/api/v1/licensing/custom-licenses') {
          return Promise.resolve(createMockResponse({ success: true }))
        }
        if (url === '/api/v1/licensing/license-expressions/validate') {
          return Promise.resolve(createMockResponse({
            status: 200,
            normalized: 'MIT',
            tokens: [{ key: 'MIT', known: true }]
          }))
        }
        return Promise.resolve(createMockResponse({}))
      })

      wrapper = mount(LicensesEditor, {
        props: {
          ...defaultProps,
          validationResponse: createValidationResponse({ unknown_tokens: ['CUSTOM_LICENSE'] })
        }
      })
      await nextTick()

      // Fill in the form
      const nameInput = wrapper.find('input[placeholder="Enter license name"]')
      const urlInput = wrapper.find('input[placeholder="https://example.com/license"]')
      const textArea = wrapper.find('textarea')
      const submitButton = wrapper.find('button[type="submit"]')

      await nameInput.setValue('My Custom License')
      await urlInput.setValue('https://example.com/custom')
      await textArea.setValue('Custom license text here')

      await submitButton.trigger('click')
      await nextTick()

      // Also try triggering submit on the form itself
      const form = wrapper.find('form')
      await form.trigger('submit')
      await nextTick()

      expect(vi.mocked($axios.post)).toHaveBeenCalledWith('/api/v1/licensing/custom-licenses', {
        key: 'CUSTOM_LICENSE',
        name: 'My Custom License',
        url: 'https://example.com/custom',
        text: 'Custom license text here'
      })
    })

    it('should show success message after custom license submission', async () => {
      // Mock the validation endpoint to not interfere
      vi.mocked($axios.post).mockImplementation((url) => {
        if (url === '/api/v1/licensing/custom-licenses') {
          return Promise.resolve(createMockResponse({ success: true }))
        }
        if (url === '/api/v1/licensing/license-expressions/validate') {
          return Promise.resolve(createMockResponse({
            status: 200,
            normalized: 'MIT',
            tokens: [{ key: 'MIT', known: true }]
          }))
        }
        return Promise.resolve(createMockResponse({}))
      })

      wrapper = mount(LicensesEditor, {
        props: {
          ...defaultProps,
          validationResponse: createValidationResponse({ unknown_tokens: ['CUSTOM_LICENSE'] })
        }
      })
      await nextTick()

      const nameInput = wrapper.find('input[placeholder="Enter license name"]')
      const submitButton = wrapper.find('button[type="submit"]')

      await nameInput.setValue('My Custom License')
      await submitButton.trigger('click')
      await nextTick()

      // Also try triggering submit on the form itself
      const form = wrapper.find('form')
      await form.trigger('submit')
      await nextTick()

      // Check for success message
      await new Promise(resolve => setTimeout(resolve, 100))
      await nextTick()

      expect(wrapper.find('.alert-success').exists()).toBe(true)
    })

    it('should handle custom license submission errors', async () => {
      const errorDetail = { url: 'Invalid URL format' }
      // Mock the validation endpoint to not interfere
      vi.mocked($axios.post).mockImplementation((url) => {
        if (url === '/api/v1/licensing/custom-licenses') {
          return Promise.reject({
            response: { data: { detail: errorDetail } }
          })
        }
        if (url === '/api/v1/licensing/license-expressions/validate') {
          return Promise.resolve(createMockResponse({
            status: 200,
            normalized: 'MIT',
            tokens: [{ key: 'MIT', known: true }]
          }))
        }
        return Promise.resolve(createMockResponse({}))
      })

      wrapper = mount(LicensesEditor, {
        props: {
          ...defaultProps,
          validationResponse: createValidationResponse({ unknown_tokens: ['CUSTOM_LICENSE'] })
        }
      })
      await nextTick()

      // Fill in the name to enable the submit button
      const nameInput = wrapper.find('input[placeholder="Enter license name"]')
      await nameInput.setValue('My Custom License')
      await nextTick()

      const submitButton = wrapper.find('button[type="submit"]')
      await submitButton.trigger('click')
      await nextTick()

      // Also try triggering submit on the form itself
      const form = wrapper.find('form')
      await form.trigger('submit')
      await nextTick()

      // Should show validation errors in UI
      expect(wrapper.find('.invalid-feedback').exists()).toBe(true)
    })

    it('should disable submit button when name is empty', async () => {
      wrapper = mount(LicensesEditor, {
        props: {
          ...defaultProps,
          validationResponse: createValidationResponse({ unknown_tokens: ['CUSTOM_LICENSE'] })
        }
      })
      await nextTick()

      const submitButton = wrapper.find('button[type="submit"]')
      expect(submitButton.attributes('disabled')).toBeDefined()

      // Add name to enable button
      const nameInput = wrapper.find('input[placeholder="Enter license name"]')
      await nameInput.setValue('My License')
      await nextTick()

      expect(submitButton.attributes('disabled')).toBeUndefined()
    })
  })

  describe('Validation States', () => {
    beforeEach(async () => {
      wrapper = mount(LicensesEditor, { props: defaultProps })
      await nextTick()
    })

    it('should show validation errors passed as props', async () => {
      await wrapper.setProps({
        validationErrors: { general: 'Something went wrong' }
      })
      await nextTick()

      // Check if error is displayed in UI
      const errorElements = wrapper.findAll('.invalid-feedback, .text-danger, .alert-danger')
      const hasError = errorElements.some(el => el.text().includes('Something went wrong'))
      expect(hasError).toBe(true)
    })

    it('should clear validation error on successful validation', async () => {
      // First set an error
      vi.mocked($axios.post).mockRejectedValueOnce({
        response: { data: { detail: 'Invalid' } }
      })

      const input = wrapper.find('input[type="text"]')
      await input.setValue('INVALID')
      await new Promise(resolve => setTimeout(resolve, 350))
      await nextTick()

      expect(wrapper.find('.invalid-feedback').exists()).toBe(true)

      // Then provide valid response
      vi.mocked($axios.post).mockResolvedValueOnce(createMockResponse({
        status: 200,
        normalized: 'MIT',
        tokens: [{ key: 'MIT', known: true }]
      }))

      await input.setValue('MIT')
      await new Promise(resolve => setTimeout(resolve, 350))
      await nextTick()

      expect(wrapper.find('.invalid-feedback').exists()).toBe(false)
    })
  })

  describe('Integration Tests', () => {
    it('should handle complete license expression workflow with Add button', async () => {
      // Setup responses for the complete workflow
      vi.mocked($axios.post)
        .mockResolvedValueOnce(createMockResponse({
          status: 200,
          normalized: 'MIT',
          tokens: [{ key: 'MIT', known: true }]
        }))
        .mockResolvedValueOnce(createMockResponse({
          status: 200,
          normalized: 'Apache-2.0 WITH Commons-Clause',
          tokens: [
            { key: 'Apache-2.0', known: true },
            { key: 'Commons-Clause', known: true }
          ]
        }))

      wrapper = mount(LicensesEditor, { props: defaultProps })
      await nextTick()

      const input = wrapper.find('input[type="text"]')
      const addButton = wrapper.find('.add-license-btn')

      // Add first license
      await input.setValue('MIT')
      await addButton.trigger('click')
      await nextTick()

      let emittedEvents = wrapper.emitted('update:modelValue') as Array<Array<(string | CustomLicense)[]>>
      expect(emittedEvents[emittedEvents.length - 1][0]).toEqual(['MIT'])

      // Add second license (complex expression)
      await input.setValue('Apache-2.0 WITH Commons-Clause')
      await addButton.trigger('click')
      await nextTick()

      emittedEvents = wrapper.emitted('update:modelValue') as Array<Array<(string | CustomLicense)[]>>
      expect(emittedEvents[emittedEvents.length - 1][0]).toEqual(['MIT', 'Apache-2.0 WITH Commons-Clause'])

      // Verify validation API calls happened
      expect(vi.mocked($axios.post)).toHaveBeenCalledWith('/api/v1/licensing/license-expressions/validate', {
        expression: 'MIT'
      })
      expect(vi.mocked($axios.post)).toHaveBeenCalledWith('/api/v1/licensing/license-expressions/validate', {
        expression: 'Apache-2.0 WITH Commons-Clause'
      })
    })

    it('should handle adding multiple licenses with Add button', async () => {
      vi.mocked($axios.post).mockResolvedValue(createMockResponse({
        status: 200,
        normalized: 'MIT',
        tokens: [{ key: 'MIT', known: true }]
      }))

      wrapper = mount(LicensesEditor, { props: defaultProps })
      await nextTick()

      const input = wrapper.find('input[type="text"]')
      const addButton = wrapper.find('.add-license-btn')

      // Add first license
      await input.setValue('MIT')
      await addButton.trigger('click')
      await nextTick()

      // Add second license
      await input.setValue('Apache-2.0')
      await addButton.trigger('click')
      await nextTick()

      // Add third license (complex expression)
      await input.setValue('GPL-3.0 WITH Commons-Clause')
      await addButton.trigger('click')
      await nextTick()

      const emittedEvents = wrapper.emitted('update:modelValue') as Array<Array<(string | CustomLicense)[]>>
      expect(emittedEvents[emittedEvents.length - 1][0]).toEqual(['MIT', 'Apache-2.0', 'GPL-3.0 WITH Commons-Clause'])
    })
  })
})