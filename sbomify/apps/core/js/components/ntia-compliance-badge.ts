import Alpine from 'alpinejs'

interface ComplianceError {
  field: string
  message: string
  suggestion: string
}

interface ComplianceDetails {
  errors?: ComplianceError[]
  checked_at?: string
  error_count?: number
}

export function registerNtiaComplianceBadge() {
  Alpine.data('ntiaComplianceBadge', (
    status: 'compliant' | 'non_compliant' | 'unknown',
    complianceDetailsJson: string,
    isPublicView: boolean,
    teamBillingPlan: string,
    teamKey: string
  ) => {
    const complianceDetails: ComplianceDetails = complianceDetailsJson 
      ? JSON.parse(complianceDetailsJson) 
      : {}

    return {
      status,
      complianceDetails,
      isPublicView,
      teamBillingPlan,
      teamKey,
      showDetailsModal: false,
      expandedIssues: [] as number[],

      get complianceErrors(): ComplianceError[] {
        return this.complianceDetails?.errors || []
      },

      get isNtiaAvailable(): boolean {
        return this.teamBillingPlan === 'business' || this.teamBillingPlan === 'enterprise'
      },

      get errorCount(): number {
        return this.complianceDetails?.error_count || this.complianceErrors.length
      },

      toggleIssue(index: number): void {
        const currentIndex = this.expandedIssues.indexOf(index)
        if (currentIndex > -1) {
          this.expandedIssues.splice(currentIndex, 1)
        } else {
          this.expandedIssues.push(index)
        }
      },

      isIssueExpanded(index: number): boolean {
        return this.expandedIssues.includes(index)
      },

      getUnknownBadgeClasses(): string {
        if (this.isNtiaAvailable) {
          return 'bg-info-subtle text-info ntia-checking'
        }
        return 'bg-secondary-subtle text-secondary'
      },

      getUnknownIconClass(): string {
        if (this.isNtiaAvailable) {
          return 'fas fa-clock fa-pulse'
        }
        return 'fas fa-lock'
      },

      getUnknownStatusText(): string {
        if (this.isNtiaAvailable) {
          return 'Checking...'
        }
        return 'Upgrade Required'
      },

      handleUnknownBadgeClick(): void {
        if (!this.isNtiaAvailable) {
          const upgradePath = this.teamKey 
            ? `/billing/select-plan/${this.teamKey}` 
            : '/billing/select-plan/'
          window.location.href = upgradePath
        }
      },

      getTooltipText(): string {
        switch (this.status) {
          case 'compliant':
            return 'This SBOM meets all NTIA minimum elements requirements'
          case 'non_compliant':
            return `This SBOM has ${this.errorCount} NTIA compliance issue${this.errorCount !== 1 ? 's' : ''}. Click for details.`
          case 'unknown':
            if (this.isNtiaAvailable) {
              return 'NTIA compliance check is being performed in the background. This usually takes a few minutes to complete.'
            }
            return 'NTIA Minimum Elements compliance is available with Business and Enterprise plans. Upgrade to unlock this feature.'
          default:
            return 'NTIA compliance status unknown'
        }
      },

      init() {
        // Initialize Bootstrap tooltips
        this.$nextTick(() => {
          const tooltipElements = this.$el.querySelectorAll('[data-bs-toggle="tooltip"]')
          if (window.bootstrap?.Tooltip) {
            Array.from(tooltipElements).forEach(el => {
              new window.bootstrap.Tooltip(el)
            })
          }
        })
      }
    }
  })
}

