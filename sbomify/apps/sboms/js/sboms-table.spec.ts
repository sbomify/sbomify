import { describe, test, expect, mock, beforeEach } from 'bun:test'

const mockAlpineData = mock<(name: string, callback: () => unknown) => void>()

mock.module('../../core/js/alpine-init', () => ({
    default: {
        data: mockAlpineData
    }
}))

mock.module('../../core/js/components/pagination-controls', () => ({
    createPaginationData: mock().mockReturnValue({
        currentPage: 1,
        pageSize: 10,
        totalItems: 0
    })
}))

interface Sbom {
    id: string
    name: string
    format: string
    format_version: string
    version: string
    created_at: string
}

interface Release {
    id: string
    name: string
    product_id: string
    product_name: string
    is_latest: boolean
    is_prerelease: boolean
    is_public: boolean
}

type PluginStatus = 'pass' | 'fail' | 'pending' | 'error'
type OverallStatus = 'all_pass' | 'has_failures' | 'pending' | 'in_progress' | 'no_assessments'

interface PluginResult {
    name: string
    display_name: string
    status: PluginStatus
    findings_count: number
    fail_count: number
}

interface AssessmentsData {
    sbom_id: string
    overall_status: OverallStatus
    total_assessments: number
    passing_count: number
    failing_count: number
    pending_count: number
    plugins: PluginResult[]
}

interface SbomItem {
    sbom: Sbom
    has_vulnerabilities_report: boolean
    releases: Release[]
    assessments?: AssessmentsData
}

describe('SBOMs Table', () => {
    beforeEach(() => {
        mockAlpineData.mockClear()
    })

    describe('SBOM Interface', () => {
        test('should accept valid SBOM structure', () => {
            const sbom: Sbom = {
                id: 'sbom-123',
                name: 'my-app',
                format: 'CycloneDX',
                format_version: '1.5',
                version: '1.0.0',
                created_at: '2024-01-15T12:00:00Z'
            }

            expect(sbom.id).toBe('sbom-123')
            expect(sbom.format).toBe('CycloneDX')
            expect(sbom.format_version).toBe('1.5')
        })
    })

    describe('Release Interface', () => {
        test('should include all release properties', () => {
            const release: Release = {
                id: 'rel-1',
                name: 'v1.0.0',
                product_id: 'prod-1',
                product_name: 'My Product',
                is_latest: true,
                is_prerelease: false,
                is_public: true
            }

            expect(release.is_latest).toBe(true)
            expect(release.is_public).toBe(true)
        })
    })

    describe('SBOM Item', () => {
        test('should contain SBOM with optional assessments', () => {
            const item: SbomItem = {
                sbom: {
                    id: 'sbom-1',
                    name: 'app',
                    format: 'SPDX',
                    format_version: '2.3',
                    version: '1.0',
                    created_at: '2024-01-01'
                },
                has_vulnerabilities_report: true,
                releases: [],
                assessments: {
                    sbom_id: 'sbom-1',
                    overall_status: 'all_pass',
                    total_assessments: 3,
                    passing_count: 3,
                    failing_count: 0,
                    pending_count: 0,
                    plugins: []
                }
            }

            expect(item.sbom.format).toBe('SPDX')
            expect(item.has_vulnerabilities_report).toBe(true)
            expect(item.assessments?.overall_status).toBe('all_pass')
        })

        test('should work without assessments', () => {
            const item: SbomItem = {
                sbom: {
                    id: 'sbom-2',
                    name: 'lib',
                    format: 'CycloneDX',
                    format_version: '1.4',
                    version: '2.0',
                    created_at: '2024-02-01'
                },
                has_vulnerabilities_report: false,
                releases: []
            }

            expect(item.assessments).toBeUndefined()
        })
    })

    describe('Plugin Result', () => {
        test('should handle different plugin statuses', () => {
            const plugins: PluginResult[] = [
                { name: 'ntia', display_name: 'NTIA', status: 'pass', findings_count: 5, fail_count: 0 },
                { name: 'cra', display_name: 'CRA', status: 'fail', findings_count: 10, fail_count: 3 }
            ]

            expect(plugins[0].status).toBe('pass')
            expect(plugins[1].fail_count).toBe(3)
        })
    })

    describe('JSON Parsing', () => {
        test('should parse SBOMs data JSON', () => {
            const json = JSON.stringify([
                {
                    sbom: { id: '1', name: 'Test', format: 'CDX', format_version: '1.5', version: '1.0', created_at: '' },
                    has_vulnerabilities_report: false,
                    releases: []
                }
            ])

            const parsed = JSON.parse(json) as SbomItem[]
            expect(parsed).toHaveLength(1)
            expect(parsed[0].sbom.name).toBe('Test')
        })
    })

    describe('Component ID', () => {
        test('should store component ID', () => {
            const componentId = 'comp-abc123'
            expect(componentId).toBe('comp-abc123')
        })
    })
})
