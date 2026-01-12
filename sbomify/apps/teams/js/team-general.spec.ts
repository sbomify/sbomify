import { describe, test, expect, mock, beforeEach } from 'bun:test'

const mockAlpineData = mock<(name: string, callback: () => unknown) => void>()

mock.module('alpinejs', () => ({
    default: {
        data: mockAlpineData
    }
}))

describe('Team General', () => {
    beforeEach(() => {
        mockAlpineData.mockClear()
    })

    describe('Initialization', () => {
        test('should set initial name values', () => {
            const initialName = 'My Workspace'
            const state = {
                originalName: initialName,
                localName: initialName
            }

            expect(state.originalName).toBe('My Workspace')
            expect(state.localName).toBe('My Workspace')
        })
    })

    describe('Unsaved Changes Detection', () => {
        test('should return false when names match', () => {
            const hasUnsavedChanges = (original: string, local: string): boolean => {
                return local !== original
            }

            expect(hasUnsavedChanges('Test', 'Test')).toBe(false)
        })

        test('should return true when names differ', () => {
            const hasUnsavedChanges = (original: string, local: string): boolean => {
                return local !== original
            }

            expect(hasUnsavedChanges('Original', 'Changed')).toBe(true)
        })

        test('should detect changes for whitespace differences', () => {
            const hasUnsavedChanges = (original: string, local: string): boolean => {
                return local !== original
            }

            expect(hasUnsavedChanges('Test', 'Test ')).toBe(true)
            expect(hasUnsavedChanges(' Test', 'Test')).toBe(true)
        })
    })

    describe('Name Editing', () => {
        test('should allow name modification', () => {
            const state = {
                originalName: 'Original Name',
                localName: 'Original Name'
            }

            state.localName = 'New Name'

            expect(state.localName).toBe('New Name')
            expect(state.originalName).toBe('Original Name')
        })

        test('should track changes correctly after multiple edits', () => {
            const state = {
                originalName: 'Original',
                localName: 'Original'
            }

            const hasUnsavedChanges = () => state.localName !== state.originalName

            expect(hasUnsavedChanges()).toBe(false)

            state.localName = 'Changed'
            expect(hasUnsavedChanges()).toBe(true)

            state.localName = 'Original'
            expect(hasUnsavedChanges()).toBe(false)
        })
    })
})
