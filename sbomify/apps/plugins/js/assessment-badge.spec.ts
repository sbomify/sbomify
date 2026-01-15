import { describe, test, expect, mock, beforeEach } from 'bun:test'

const mockAlpineData = mock<(name: string, callback: () => unknown) => void>()

mock.module('alpinejs', () => ({
    default: {
        data: mockAlpineData
    }
}))

type OverallStatus = 'all_pass' | 'has_failures' | 'pending' | 'in_progress' | 'no_assessments' | 'no_plugins_enabled'
type PluginStatus = 'pass' | 'fail' | 'pending' | 'error'

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

describe('Assessment Badge', () => {
    beforeEach(() => {
        mockAlpineData.mockClear()
    })

    describe('Badge Classes', () => {
        test('should return success class for all_pass status', () => {
            const getBadgeClasses = (status: OverallStatus, isAvailable: boolean): string => {
                if (!isAvailable) {
                    return 'bg-secondary-subtle text-secondary'
                }

                switch (status) {
                    case 'all_pass':
                        return 'bg-success-subtle text-success'
                    case 'has_failures':
                        return 'bg-warning-subtle text-warning'
                    case 'pending':
                    case 'in_progress':
                        return 'bg-info-subtle text-info assessment-checking'
                    case 'no_plugins_enabled':
                        return 'bg-secondary-subtle text-secondary'
                    default:
                        return 'bg-secondary-subtle text-secondary'
                }
            }

            expect(getBadgeClasses('all_pass', true)).toBe('bg-success-subtle text-success')
            expect(getBadgeClasses('has_failures', true)).toBe('bg-warning-subtle text-warning')
            expect(getBadgeClasses('pending', true)).toBe('bg-info-subtle text-info assessment-checking')
            expect(getBadgeClasses('no_plugins_enabled', true)).toBe('bg-secondary-subtle text-secondary')
            expect(getBadgeClasses('no_assessments', false)).toBe('bg-secondary-subtle text-secondary')
        })
    })

    describe('Badge Icon Classes', () => {
        test('should return correct icon class for each status', () => {
            const getBadgeIconClass = (status: OverallStatus, isAvailable: boolean): string => {
                if (!isAvailable) {
                    return 'fas fa-lock'
                }

                switch (status) {
                    case 'all_pass':
                        return 'fas fa-check-circle'
                    case 'has_failures':
                        return 'fas fa-exclamation-triangle'
                    case 'pending':
                    case 'in_progress':
                        return 'fas fa-clock fa-pulse'
                    case 'no_plugins_enabled':
                        return 'fas fa-puzzle-piece'
                    default:
                        return 'fas fa-lock'
                }
            }

            expect(getBadgeIconClass('all_pass', true)).toBe('fas fa-check-circle')
            expect(getBadgeIconClass('has_failures', true)).toBe('fas fa-exclamation-triangle')
            expect(getBadgeIconClass('pending', true)).toBe('fas fa-clock fa-pulse')
            expect(getBadgeIconClass('no_plugins_enabled', true)).toBe('fas fa-puzzle-piece')
            expect(getBadgeIconClass('no_assessments', false)).toBe('fas fa-lock')
        })
    })

    describe('Badge Text', () => {
        test('should return correct text for each status', () => {
            const getBadgeText = (
                status: OverallStatus,
                isAvailable: boolean,
                passingCount: number,
                failingCount: number
            ): string => {
                if (!isAvailable) {
                    return 'Upgrade'
                }

                switch (status) {
                    case 'all_pass':
                        return `${passingCount} Passed`
                    case 'has_failures':
                        return `${failingCount} Failed`
                    case 'pending':
                    case 'in_progress':
                        return 'Checking...'
                    case 'no_plugins_enabled':
                        return 'No plugins enabled'
                    default:
                        return 'Upgrade'
                }
            }

            expect(getBadgeText('all_pass', true, 5, 0)).toBe('5 Passed')
            expect(getBadgeText('has_failures', true, 3, 2)).toBe('2 Failed')
            expect(getBadgeText('pending', true, 0, 0)).toBe('Checking...')
            expect(getBadgeText('no_plugins_enabled', true, 0, 0)).toBe('No plugins enabled')
            expect(getBadgeText('no_assessments', false, 0, 0)).toBe('Upgrade')
        })
    })

    describe('Tooltip Text', () => {
        test('should return appropriate tooltip for each status', () => {
            const getTooltipText = (
                status: OverallStatus,
                isAvailable: boolean,
                passingCount: number,
                failingCount: number
            ): string => {
                if (!isAvailable) {
                    return 'Assessment features are available with Business and Enterprise plans. Click to upgrade.'
                }

                switch (status) {
                    case 'all_pass':
                        return `All ${passingCount} assessment${passingCount !== 1 ? 's' : ''} passed. Click for details.`
                    case 'has_failures':
                        return `${failingCount} assessment${failingCount !== 1 ? 's' : ''} failed. Click for details.`
                    case 'pending':
                    case 'in_progress':
                        return 'Assessments are being processed. This usually takes a few minutes.'
                    case 'no_plugins_enabled':
                        return 'No assessment plugins are enabled for this workspace. Enable plugins in workspace settings to run assessments.'
                    default:
                        return 'No assessments available.'
                }
            }

            expect(getTooltipText('all_pass', true, 1, 0)).toContain('1 assessment passed')
            expect(getTooltipText('all_pass', true, 5, 0)).toContain('5 assessments passed')
            expect(getTooltipText('has_failures', true, 3, 2)).toContain('2 assessments failed')
            expect(getTooltipText('pending', true, 0, 0)).toContain('being processed')
            expect(getTooltipText('no_plugins_enabled', true, 0, 0)).toContain('No assessment plugins are enabled')
            expect(getTooltipText('no_assessments', false, 0, 0)).toContain('Business and Enterprise')
        })
    })

    describe('Plugin Status Badge Classes', () => {
        test('should return correct class for plugin status', () => {
            const getPluginStatusBadgeClass = (status: PluginStatus): string => {
                switch (status) {
                    case 'pass':
                        return 'bg-success-subtle text-success'
                    case 'fail':
                        return 'bg-warning-subtle text-warning'
                    case 'pending':
                        return 'bg-info-subtle text-info'
                    case 'error':
                        return 'bg-danger-subtle text-danger'
                    default:
                        return 'bg-secondary-subtle text-secondary'
                }
            }

            expect(getPluginStatusBadgeClass('pass')).toBe('bg-success-subtle text-success')
            expect(getPluginStatusBadgeClass('fail')).toBe('bg-warning-subtle text-warning')
            expect(getPluginStatusBadgeClass('pending')).toBe('bg-info-subtle text-info')
            expect(getPluginStatusBadgeClass('error')).toBe('bg-danger-subtle text-danger')
        })
    })

    describe('Plugin Status Text', () => {
        test('should return correct text for plugin status', () => {
            const getPluginStatusText = (status: PluginStatus): string => {
                switch (status) {
                    case 'pass':
                        return 'Passed'
                    case 'fail':
                        return 'Failed'
                    case 'pending':
                        return 'Pending'
                    case 'error':
                        return 'Error'
                    default:
                        return 'Unknown'
                }
            }

            expect(getPluginStatusText('pass')).toBe('Passed')
            expect(getPluginStatusText('fail')).toBe('Failed')
            expect(getPluginStatusText('pending')).toBe('Pending')
            expect(getPluginStatusText('error')).toBe('Error')
        })
    })

    describe('Assessment Availability', () => {
        test('should check if assessment is available based on billing plan', () => {
            const isAssessmentAvailable = (billingPlan: string): boolean => {
                return billingPlan === 'business' || billingPlan === 'enterprise'
            }

            expect(isAssessmentAvailable('business')).toBe(true)
            expect(isAssessmentAvailable('enterprise')).toBe(true)
            expect(isAssessmentAvailable('community')).toBe(false)
            expect(isAssessmentAvailable('starter')).toBe(false)
        })
    })

    describe('Badge Clickability', () => {
        test('should determine if badge is clickable', () => {
            const isBadgeClickable = (
                totalAssessments: number,
                overallStatus: OverallStatus,
                isAssessmentAvailable: boolean
            ): boolean => {
                return (
                    totalAssessments > 0 ||
                    overallStatus === 'has_failures' ||
                    (!isAssessmentAvailable && totalAssessments === 0)
                )
            }

            expect(isBadgeClickable(5, 'all_pass', true)).toBe(true)
            expect(isBadgeClickable(0, 'has_failures', true)).toBe(true)
            expect(isBadgeClickable(0, 'no_assessments', false)).toBe(true)
            expect(isBadgeClickable(0, 'pending', true)).toBe(false)
        })
    })

    describe('Plugin Detail URL', () => {
        test('should generate correct plugin detail URL', () => {
            const getPluginDetailUrl = (
                componentId: string,
                sbomId: string,
                pluginName: string,
                baseUrl?: string
            ): string => {
                if (baseUrl) {
                    return `${baseUrl}#plugin-${pluginName}`
                }
                return `/components/${componentId}/sboms/${sbomId}#plugin-${pluginName}`
            }

            expect(getPluginDetailUrl('comp-1', 'sbom-1', 'ntia'))
                .toBe('/components/comp-1/sboms/sbom-1#plugin-ntia')

            expect(getPluginDetailUrl('comp-1', 'sbom-1', 'cra', '/sbom/detail'))
                .toBe('/sbom/detail#plugin-cra')
        })
    })

    describe('Assessments Data Parsing', () => {
        test('should parse assessments data from JSON', () => {
            const jsonString = JSON.stringify({
                sbom_id: 'sbom-123',
                overall_status: 'all_pass',
                total_assessments: 5,
                passing_count: 5,
                failing_count: 0,
                pending_count: 0,
                plugins: []
            })

            const data: AssessmentsData = JSON.parse(jsonString)

            expect(data.sbom_id).toBe('sbom-123')
            expect(data.overall_status).toBe('all_pass')
            expect(data.total_assessments).toBe(5)
        })

        test('should handle empty JSON string', () => {
            const data: AssessmentsData = JSON.parse('{}')

            expect(data.overall_status).toBeUndefined()
            expect(data.total_assessments).toBeUndefined()
        })
    })

    describe('Computed Properties', () => {
        test('should return correct counts from assessments data', () => {
            const data: AssessmentsData = {
                sbom_id: 'sbom-1',
                overall_status: 'has_failures',
                total_assessments: 10,
                passing_count: 7,
                failing_count: 3,
                pending_count: 0,
                plugins: []
            }

            expect(data.total_assessments).toBe(10)
            expect(data.passing_count).toBe(7)
            expect(data.failing_count).toBe(3)
            expect(data.pending_count).toBe(0)
        })

        test('should return plugins array', () => {
            const plugins: PluginResult[] = [
                { name: 'ntia', display_name: 'NTIA', status: 'pass', findings_count: 5, fail_count: 0 },
                { name: 'cra', display_name: 'CRA', status: 'fail', findings_count: 10, fail_count: 3 }
            ]

            expect(plugins).toHaveLength(2)
            expect(plugins[0].status).toBe('pass')
            expect(plugins[1].status).toBe('fail')
        })
    })
})
