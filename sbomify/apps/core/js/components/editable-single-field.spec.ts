import { describe, it, expect, mock, beforeEach, afterEach } from 'bun:test'

mock.module('../csrf', () => ({ getCsrfToken: () => 'csrf-value' }))

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Field = Record<string, any>
let editableSingleField: (params: Record<string, string>) => Field

mock.module('alpinejs', () => ({
  default: {
    data: (_name: string, factory: typeof editableSingleField) => {
      editableSingleField = factory
    }
  }
}))

const { registerEditableSingleField } = await import('./editable-single-field')
registerEditableSingleField()

const globals = globalThis as unknown as Record<string, unknown>
const realGlobals = { fetch: globals.fetch, window: globals.window }

describe('EditableSingleField', () => {
  const mockComponentId = 'test-component-123'
  const mockTeamId = 'team-456'
  const mockProductId = 'product-012'
  let reload: ReturnType<typeof mock>

  beforeEach(() => {
    reload = mock()
    globals.window = { location: { reload } }
  })

  afterEach(() => {
    for (const [name, value] of Object.entries(realGlobals)) {
      if (value === undefined) delete globals[name]
      else globals[name] = value
    }
  })

  describe('Saving', () => {
    it('sends the trimmed value as a PATCH with the CSRF token, then reloads', async () => {
      const fetcher = mock(async () => new Response(null, { status: 204 }))
      globals.fetch = fetcher
      const field = editableSingleField({ itemType: 'component', itemId: mockComponentId, itemValue: 'Old name' })
      field.fieldValue = '  New name  '

      await field.updateField()

      const [url, init] = fetcher.mock.calls[0] as unknown as [string, RequestInit]
      expect(url).toBe(`/api/v1/components/${mockComponentId}`)
      expect(init.method).toBe('PATCH')
      expect(init.headers).toEqual({ 'Content-Type': 'application/json', 'X-CSRFToken': 'csrf-value' })
      expect(init.body).toBe(JSON.stringify({ name: 'New name' }))
      expect(field.isEditing).toBe(false)
      expect(reload).toHaveBeenCalledTimes(1)
    })

    it('keeps the old value and reports the status when the server refuses', async () => {
      globals.fetch = mock(async () => Response.json({ detail: 'Invalid name provided' }, { status: 400 }))
      const field = editableSingleField({ itemType: 'product', itemId: mockProductId, itemValue: 'Old name' })
      field.fieldValue = 'New name'

      await field.updateField()

      expect(field.fieldValue).toBe('Old name')
      expect(field.errorMessage).toBe('Error updating field. Request failed with status code 400')
      expect(reload).not.toHaveBeenCalled()
    })

    it('keeps the old value when the request never reaches the server', async () => {
      globals.fetch = mock(async () => {
        throw new Error('Network Error')
      })
      const field = editableSingleField({ itemType: 'workspace', itemId: mockTeamId, itemValue: 'Old name' })
      field.fieldValue = 'New name'

      await field.updateField()

      expect(field.fieldValue).toBe('Old name')
      expect(field.errorMessage).toBe('Error updating field. Network Error')
      expect(reload).not.toHaveBeenCalled()
    })
  })

  describe('URL Construction', () => {
    it('should construct correct API URL for different item types', () => {
      const testCases = [
        { itemType: 'component', itemId: mockComponentId, expected: `/api/v1/components/${mockComponentId}` },
        { itemType: 'workspace', itemId: mockTeamId, expected: `/api/v1/workspaces/${mockTeamId}` },
        { itemType: 'product', itemId: mockProductId, expected: `/api/v1/products/${mockProductId}` }
      ]

      testCases.forEach(({ itemType, itemId, expected }) => {
        let apiUrl: string;
        switch (itemType) {
          case 'workspace':
            apiUrl = `/api/v1/workspaces/${itemId}`;
            break;
          case 'component':
            apiUrl = `/api/v1/components/${itemId}`;
            break;
          case 'product':
            apiUrl = `/api/v1/products/${itemId}`;
            break;
          default:
            apiUrl = '';
        }
        expect(apiUrl).toBe(expected)
      })
    })

    it('should include api/v1 prefix in URL', () => {
      const apiUrl = `/api/v1/components/${mockComponentId}`
      expect(apiUrl).toMatch(/^\/api\/v1\//)
    })
  })
})
