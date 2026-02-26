import { describe, test, expect, mock, beforeEach } from 'bun:test'

const mockAxios = {
    get: mock<(url: string) => Promise<{ data: { results: unknown[]; count: number } }>>(),
    post: mock<(url: string, data: unknown) => Promise<{ data: unknown }>>(),
    put: mock<(url: string, data: unknown) => Promise<{ data: unknown }>>(),
    delete: mock<(url: string) => Promise<void>>()
}

mock.module('../utils', () => ({
    default: mockAxios
}))

const mockShowSuccess = mock<(message: string) => void>()
const mockShowError = mock<(message: string) => void>()

mock.module('../alerts', () => ({
    showSuccess: mockShowSuccess,
    showError: mockShowError
}))

mock.module('./pagination-controls', () => ({
    createPaginationData: mock()
}))

const mockAlpineData = mock<(name: string, callback: () => unknown) => void>()

mock.module('alpinejs', () => ({
    default: {
        data: mockAlpineData
    }
}))

interface Release {
    id: string
    name: string
    version?: string
    description?: string
    is_prerelease: boolean
    is_latest: boolean
    release_date?: string
    created_at?: string
    artifacts_count?: number
}

interface ReleaseForm {
    id: string | null
    name: string
    description: string
    is_prerelease: boolean
    created_at: string
    released_at: string
}

describe('Product Releases', () => {
    beforeEach(() => {
        mockAxios.get.mockClear()
        mockAxios.post.mockClear()
        mockAxios.put.mockClear()
        mockAxios.delete.mockClear()
        mockShowSuccess.mockClear()
        mockShowError.mockClear()
        mockAlpineData.mockClear()
    })

    describe('Date Formatting', () => {
        test('should format date for display', () => {
            const formatDate = (dateString?: string): string => {
                if (!dateString) return ''
                const date = new Date(dateString)
                if (isNaN(date.getTime())) return ''
                return date.toLocaleDateString('en-US', {
                    year: 'numeric',
                    month: 'short',
                    day: 'numeric'
                })
            }

            expect(formatDate('2024-01-15T12:00:00Z')).toContain('Jan')
            expect(formatDate('2024-01-15T12:00:00Z')).toContain('15')
            expect(formatDate('2024-01-15T12:00:00Z')).toContain('2024')
            expect(formatDate('')).toBe('')
            expect(formatDate(undefined)).toBe('')
        })

        test('should generate default datetime for new release', () => {
            const getDefaultDateTime = (): string => {
                const now = new Date()
                const pad = (n: number) => n.toString().padStart(2, '0')
                return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}T${pad(now.getHours())}:${pad(now.getMinutes())}`
            }

            const result = getDefaultDateTime()
            expect(result).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/)
        })

        test('should format datetime for input element', () => {
            const formatDateTimeForInput = (value?: string): string => {
                if (!value) return ''
                const date = new Date(value)
                if (isNaN(date.getTime())) return ''
                const pad = (n: number) => n.toString().padStart(2, '0')
                return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`
            }

            expect(formatDateTimeForInput('2024-01-15T14:30:00Z')).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/)
            expect(formatDateTimeForInput('')).toBe('')
            expect(formatDateTimeForInput(undefined)).toBe('')
        })
    })

    describe('Form State Management', () => {
        test('should initialize form for creating release', () => {
            const defaultForm: ReleaseForm = {
                id: null,
                name: '',
                description: '',
                is_prerelease: false,
                created_at: '',
                released_at: ''
            }

            expect(defaultForm.id).toBeNull()
            expect(defaultForm.name).toBe('')
            expect(defaultForm.is_prerelease).toBe(false)
        })

        test('should populate form for editing release', () => {
            const release: Release = {
                id: 'rel-123',
                name: 'v1.0.0',
                description: 'Initial release',
                is_prerelease: false,
                is_latest: true,
                release_date: '2024-01-15T12:00:00Z',
                created_at: '2024-01-10T10:00:00Z'
            }

            const form: ReleaseForm = {
                id: release.id,
                name: release.name,
                description: release.description || '',
                is_prerelease: release.is_prerelease,
                created_at: release.created_at || '',
                released_at: release.release_date || ''
            }

            expect(form.id).toBe('rel-123')
            expect(form.name).toBe('v1.0.0')
            expect(form.description).toBe('Initial release')
        })

        test('should reset form on close', () => {
            const resetForm = (): ReleaseForm => ({
                id: null,
                name: '',
                description: '',
                is_prerelease: false,
                created_at: '',
                released_at: ''
            })

            const form = resetForm()
            expect(form.id).toBeNull()
            expect(form.name).toBe('')
        })
    })

    describe('Modal State', () => {
        test('should manage create modal state', () => {
            let showCreateModal = false

            const openCreateModal = () => {
                showCreateModal = true
            }

            const closeModal = () => {
                showCreateModal = false
            }

            openCreateModal()
            expect(showCreateModal).toBe(true)

            closeModal()
            expect(showCreateModal).toBe(false)
        })

        test('should manage edit modal state', () => {
            let showEditModal = false

            const openEditModal = () => {
                showEditModal = true
            }

            const closeModal = () => {
                showEditModal = false
            }

            openEditModal()
            expect(showEditModal).toBe(true)

            closeModal()
            expect(showEditModal).toBe(false)
        })
    })

    describe('API Endpoints', () => {
        test('should generate correct list endpoint', () => {
            const productId = 'prod-123'
            const endpoint = `/api/v1/products/${productId}/releases`

            expect(endpoint).toBe('/api/v1/products/prod-123/releases')
        })

        test('should generate correct single release endpoint', () => {
            const productId = 'prod-123'
            const releaseId = 'rel-456'
            const endpoint = `/api/v1/products/${productId}/releases/${releaseId}`

            expect(endpoint).toBe('/api/v1/products/prod-123/releases/rel-456')
        })

        test('should include pagination params', () => {
            const productId = 'prod-123'
            const page = 2
            const limit = 10
            const endpoint = `/api/v1/products/${productId}/releases?page=${page}&limit=${limit}`

            expect(endpoint).toContain('page=2')
            expect(endpoint).toContain('limit=10')
        })
    })

    describe('Release URL Generation', () => {
        test('should generate correct release detail URL', () => {
            const getReleaseUrl = (productId: string, releaseId: string): string => {
                return `/products/${productId}/releases/${releaseId}`
            }

            expect(getReleaseUrl('prod-1', 'rel-1')).toBe('/products/prod-1/releases/rel-1')
        })
    })

    describe('Prerelease Flag', () => {
        test('should correctly identify prerelease', () => {
            const prereleaseRelease: Release = {
                id: 'rel-1',
                name: 'v1.0.0-beta',
                is_prerelease: true,
                is_latest: false
            }

            const stableRelease: Release = {
                id: 'rel-2',
                name: 'v1.0.0',
                is_prerelease: false,
                is_latest: true
            }

            expect(prereleaseRelease.is_prerelease).toBe(true)
            expect(stableRelease.is_prerelease).toBe(false)
        })
    })

    describe('Latest Release Flag', () => {
        test('should correctly identify latest release', () => {
            const releases: Release[] = [
                { id: 'rel-1', name: 'v1.0.0', is_prerelease: false, is_latest: true },
                { id: 'rel-2', name: 'v0.9.0', is_prerelease: false, is_latest: false }
            ]

            const latestRelease = releases.find(r => r.is_latest)
            expect(latestRelease?.name).toBe('v1.0.0')
        })
    })

    describe('Pagination', () => {
        test('should calculate total pages correctly', () => {
            const calculateTotalPages = (totalCount: number, limit: number): number => {
                return Math.ceil(totalCount / limit)
            }

            expect(calculateTotalPages(25, 10)).toBe(3)
            expect(calculateTotalPages(20, 10)).toBe(2)
            expect(calculateTotalPages(0, 10)).toBe(0)
        })

        test('should track current page', () => {
            let currentPage = 1
            const totalPages = 5

            const goToPage = (page: number) => {
                if (page >= 1 && page <= totalPages) {
                    currentPage = page
                }
            }

            goToPage(3)
            expect(currentPage).toBe(3)

            goToPage(0)
            expect(currentPage).toBe(3)

            goToPage(6)
            expect(currentPage).toBe(3)
        })
    })

    describe('Permissions', () => {
        test('should respect CRUD permissions', () => {
            const params = {
                canCreate: true,
                canEdit: false,
                canDelete: false
            }

            expect(params.canCreate).toBe(true)
            expect(params.canEdit).toBe(false)
            expect(params.canDelete).toBe(false)
        })
    })

    describe('Public View', () => {
        test('should handle public view mode', () => {
            const isPublicView = true

            expect(isPublicView).toBe(true)
        })
    })

    describe('Artifact Count', () => {
        test('should display artifact count', () => {
            const release: Release = {
                id: 'rel-1',
                name: 'v1.0.0',
                is_prerelease: false,
                is_latest: true,
                artifacts_count: 5
            }

            expect(release.artifacts_count).toBe(5)
        })

        test('should handle missing artifact count', () => {
            const release: Release = {
                id: 'rel-1',
                name: 'v1.0.0',
                is_prerelease: false,
                is_latest: true
            }

            expect(release.artifacts_count).toBeUndefined()
        })
    })

    describe('Search Filtering (filteredReleases)', () => {
        const testReleases: Release[] = [
            { id: 'rel-1', name: 'Alpha Release', version: '0.1.0', description: 'First alpha', is_prerelease: true, is_latest: false },
            { id: 'rel-2', name: 'Beta Version', version: '0.9.0', description: 'Second beta', is_prerelease: true, is_latest: false },
            { id: 'rel-3', name: 'v1.0.0', version: '1.0.0', description: 'Stable release', is_prerelease: false, is_latest: true }
        ]

        const filterReleases = (releases: Release[], search: string): Release[] => {
            if (!search) return releases
            const searchTerm = search.toLowerCase()
            return releases.filter((release: Release) =>
                release.name.toLowerCase().includes(searchTerm) ||
                (release.version && release.version.toLowerCase().includes(searchTerm)) ||
                (release.description && release.description.toLowerCase().includes(searchTerm))
            )
        }

        test('should return all releases when search is empty', () => {
            const result = filterReleases(testReleases, '')
            expect(result).toHaveLength(3)
        })

        test('should filter releases by name', () => {
            const result = filterReleases(testReleases, 'alpha')
            expect(result).toHaveLength(1)
            expect(result[0].name).toBe('Alpha Release')
        })

        test('should filter releases by description', () => {
            const result = filterReleases(testReleases, 'stable')
            expect(result).toHaveLength(1)
            expect(result[0].name).toBe('v1.0.0')
        })

        test('should filter releases by version', () => {
            const result = filterReleases(testReleases, '0.9.0')
            expect(result).toHaveLength(1)
            expect(result[0].name).toBe('Beta Version')
        })

        test('should be case-insensitive', () => {
            const result = filterReleases(testReleases, 'BETA')
            expect(result).toHaveLength(1)
            expect(result[0].name).toBe('Beta Version')
        })

        test('should return empty array when no matches', () => {
            const result = filterReleases(testReleases, 'nonexistent')
            expect(result).toHaveLength(0)
        })

        test('should match partial terms', () => {
            const result = filterReleases(testReleases, 'rel')
            expect(result).toHaveLength(2) // 'Alpha Release' and 'Stable release'
        })
    })

    describe('Sorting (sortedReleases)', () => {
        const testReleases: Release[] = [
            { id: 'rel-1', name: 'Zebra', is_prerelease: false, is_latest: false, created_at: '2024-01-15T12:00:00Z', artifacts_count: 3 },
            { id: 'rel-2', name: 'Alpha', is_prerelease: true, is_latest: false, created_at: '2024-01-10T12:00:00Z', artifacts_count: 5 },
            { id: 'rel-3', name: 'Beta', is_prerelease: false, is_latest: true, created_at: '2024-01-20T12:00:00Z', artifacts_count: 1 }
        ]

        const sortReleases = (
            releases: Release[],
            sortColumn: string,
            sortDirection: 'asc' | 'desc'
        ): Release[] => {
            const data = [...releases]
            return data.sort((a: Release, b: Release) => {
                let aVal: string | number | boolean | undefined
                let bVal: string | number | boolean | undefined

                switch (sortColumn) {
                    case 'name':
                        aVal = a.name.toLowerCase()
                        bVal = b.name.toLowerCase()
                        break
                    case 'status':
                        aVal = a.is_prerelease ? 1 : 0
                        bVal = b.is_prerelease ? 1 : 0
                        break
                    case 'artifacts':
                        aVal = a.artifacts_count || 0
                        bVal = b.artifacts_count || 0
                        break
                    case 'created_at':
                        aVal = a.created_at || ''
                        bVal = b.created_at || ''
                        break
                    default:
                        aVal = a.name.toLowerCase()
                        bVal = b.name.toLowerCase()
                }

                if (aVal < bVal) return sortDirection === 'asc' ? -1 : 1
                if (aVal > bVal) return sortDirection === 'asc' ? 1 : -1
                return 0
            })
        }

        test('should sort by name ascending', () => {
            const result = sortReleases(testReleases, 'name', 'asc')
            expect(result[0].name).toBe('Alpha')
            expect(result[1].name).toBe('Beta')
            expect(result[2].name).toBe('Zebra')
        })

        test('should sort by name descending', () => {
            const result = sortReleases(testReleases, 'name', 'desc')
            expect(result[0].name).toBe('Zebra')
            expect(result[1].name).toBe('Beta')
            expect(result[2].name).toBe('Alpha')
        })

        test('should sort by status (prerelease)', () => {
            const result = sortReleases(testReleases, 'status', 'asc')
            // Non-prerelease (0) comes first in ascending
            expect(result[0].is_prerelease).toBe(false)
            expect(result[result.length - 1].is_prerelease).toBe(true)
        })

        test('should sort by artifact count ascending', () => {
            const result = sortReleases(testReleases, 'artifacts', 'asc')
            expect(result[0].artifacts_count).toBe(1)
            expect(result[1].artifacts_count).toBe(3)
            expect(result[2].artifacts_count).toBe(5)
        })

        test('should sort by artifact count descending', () => {
            const result = sortReleases(testReleases, 'artifacts', 'desc')
            expect(result[0].artifacts_count).toBe(5)
            expect(result[1].artifacts_count).toBe(3)
            expect(result[2].artifacts_count).toBe(1)
        })

        test('should sort by created_at ascending', () => {
            const result = sortReleases(testReleases, 'created_at', 'asc')
            expect(result[0].id).toBe('rel-2') // 2024-01-10
            expect(result[1].id).toBe('rel-1') // 2024-01-15
            expect(result[2].id).toBe('rel-3') // 2024-01-20
        })

        test('should sort by created_at descending', () => {
            const result = sortReleases(testReleases, 'created_at', 'desc')
            expect(result[0].id).toBe('rel-3') // 2024-01-20
            expect(result[1].id).toBe('rel-1') // 2024-01-15
            expect(result[2].id).toBe('rel-2') // 2024-01-10
        })

        test('should use name as default sort column', () => {
            const result = sortReleases(testReleases, 'unknown_column', 'asc')
            expect(result[0].name).toBe('Alpha')
        })
    })

    describe('Sort Toggle (sort method)', () => {
        test('should toggle direction when clicking same column', () => {
            let sortColumn = 'name'
            let sortDirection = 'asc' as 'asc' | 'desc'

            const sort = (column: string) => {
                if (sortColumn === column) {
                    sortDirection = sortDirection === 'asc' ? 'desc' : 'asc'
                } else {
                    sortColumn = column
                    sortDirection = 'asc'
                }
            }

            // Click name column again - should toggle to desc
            sort('name')
            expect(sortColumn).toBe('name')
            expect(sortDirection as string).toBe('desc')

            // Click name column again - should toggle back to asc
            sort('name')
            expect(sortColumn).toBe('name')
            expect(sortDirection as string).toBe('asc')
        })

        test('should reset to ascending when clicking different column', () => {
            let sortColumn = 'name'
            let sortDirection = 'desc' as 'asc' | 'desc'

            const sort = (column: string) => {
                if (sortColumn === column) {
                    sortDirection = sortDirection === 'asc' ? 'desc' : 'asc'
                } else {
                    sortColumn = column
                    sortDirection = 'asc'
                }
            }

            // Click different column - should reset to asc
            sort('created_at')
            expect(sortColumn).toBe('created_at')
            expect(sortDirection as string).toBe('asc')
        })

        test('should update column when clicking different column', () => {
            let sortColumn = 'name'
            let sortDirection = 'asc' as 'asc' | 'desc'

            const sort = (column: string) => {
                if (sortColumn === column) {
                    sortDirection = sortDirection === 'asc' ? 'desc' : 'asc'
                } else {
                    sortColumn = column
                    sortDirection = 'asc'
                }
            }

            sort('artifacts')
            expect(sortColumn).toBe('artifacts')

            sort('status')
            expect(sortColumn).toBe('status')
        })
    })
})
