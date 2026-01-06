import Alpine from 'alpinejs'

interface PluginResult {
  name: string
  display_name: string
  status: 'pass' | 'fail' | 'pending' | 'error'
  findings_count: number
  fail_count: number
}

interface AssessmentsData {
  sbom_id: string
  overall_status: 'all_pass' | 'has_failures' | 'pending' | 'in_progress' | 'no_assessments'
  total_assessments: number
  passing_count: number
  failing_count: number
  pending_count: number
  plugins: PluginResult[]
}

export function registerAssessmentBadge() {
  Alpine.data('assessmentBadge', (
    sbomId: string,
    componentId: string,
    assessmentsDataJson: string,
    teamBillingPlan: string,
  ) => {
    const assessmentsData: AssessmentsData = JSON.parse(assessmentsDataJson || '{}')

    return {
      sbomId,
      componentId,
      teamBillingPlan,
      showDetailsModal: false,

      // Computed from assessments data
      get overallStatus(): string {
        return assessmentsData.overall_status || 'no_assessments'
      },

      get totalAssessments(): number {
        return assessmentsData.total_assessments || 0
      },

      get passingCount(): number {
        return assessmentsData.passing_count || 0
      },

      get failingCount(): number {
        return assessmentsData.failing_count || 0
      },

      get pendingCount(): number {
        return assessmentsData.pending_count || 0
      },

      get plugins(): PluginResult[] {
        return assessmentsData.plugins || []
      },

      get isAssessmentAvailable(): boolean {
        return this.teamBillingPlan === 'business' || this.teamBillingPlan === 'enterprise'
      },

      getBadgeClasses(): string {
        if (!this.isAssessmentAvailable && this.totalAssessments === 0) {
          return 'bg-secondary-subtle text-secondary'
        }

        switch (this.overallStatus) {
          case 'all_pass':
            return 'bg-success-subtle text-success'
          case 'has_failures':
            return 'bg-warning-subtle text-warning'
          case 'pending':
          case 'in_progress':
            return 'bg-info-subtle text-info assessment-checking'
          case 'no_assessments':
          default:
            if (this.isAssessmentAvailable) {
              return 'bg-info-subtle text-info assessment-checking'
            }
            return 'bg-secondary-subtle text-secondary'
        }
      },

      getBadgeIconClass(): string {
        if (!this.isAssessmentAvailable && this.totalAssessments === 0) {
          return 'fas fa-lock'
        }

        switch (this.overallStatus) {
          case 'all_pass':
            return 'fas fa-check-circle'
          case 'has_failures':
            return 'fas fa-exclamation-triangle'
          case 'pending':
          case 'in_progress':
            return 'fas fa-clock fa-pulse'
          case 'no_assessments':
          default:
            if (this.isAssessmentAvailable) {
              return 'fas fa-clock fa-pulse'
            }
            return 'fas fa-lock'
        }
      },

      getBadgeText(): string {
        if (!this.isAssessmentAvailable && this.totalAssessments === 0) {
          return 'Upgrade'
        }

        switch (this.overallStatus) {
          case 'all_pass':
            return `${this.passingCount} Passed`
          case 'has_failures':
            return `${this.failingCount} Failed`
          case 'pending':
          case 'in_progress':
            return 'Checking...'
          case 'no_assessments':
          default:
            if (this.isAssessmentAvailable) {
              return 'Checking...'
            }
            return 'Upgrade'
        }
      },

      isBadgeClickable(): boolean {
        // Clickable if there are assessments to show, or if upgrade is needed
        return this.totalAssessments > 0 ||
               this.overallStatus === 'has_failures' ||
               (!this.isAssessmentAvailable && this.totalAssessments === 0)
      },

      getTooltipText(): string {
        if (!this.isAssessmentAvailable && this.totalAssessments === 0) {
          return 'Assessment features are available with Business and Enterprise plans. Click to upgrade.'
        }

        switch (this.overallStatus) {
          case 'all_pass':
            return `All ${this.passingCount} assessment${this.passingCount !== 1 ? 's' : ''} passed. Click for details.`
          case 'has_failures':
            return `${this.failingCount} assessment${this.failingCount !== 1 ? 's' : ''} failed. Click for details.`
          case 'pending':
          case 'in_progress':
            return 'Assessments are being processed. This usually takes a few minutes.'
          case 'no_assessments':
          default:
            if (this.isAssessmentAvailable) {
              return 'Assessments are being processed.'
            }
            return 'No assessments available.'
        }
      },

      getPluginStatusBadgeClass(status: string): string {
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
      },

      getPluginStatusText(status: string): string {
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
      },

      initModal(element: HTMLElement): void {
        element.style.display = 'block'
        if (element.parentElement !== document.body) {
          document.body.appendChild(element)
        }
      },

      getPluginDetailUrl(pluginName: string): string {
        // Build URL to SBOM detail page with anchor to specific plugin
        // Note: URL pattern matches Django's core:component_item URL
        return `/components/${this.componentId}/sboms/${this.sbomId}/#plugin-${pluginName}`
      },
    }
  })
}

