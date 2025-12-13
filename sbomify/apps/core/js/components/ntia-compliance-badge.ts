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
    teamBillingPlan: string,
  ) => {
    const complianceDetails: ComplianceDetails = JSON.parse(complianceDetailsJson);
 
    return {
      status,
      complianceDetails,
      teamBillingPlan,
      showDetailsModal: false,

      get complianceErrors(): ComplianceError[] {
        return this.complianceDetails?.errors || []
      },

      get isNtiaAvailable(): boolean {
        return this.teamBillingPlan === 'business' || this.teamBillingPlan === 'enterprise'
      },

      get errorCount(): number {
        return this.complianceDetails?.error_count || this.complianceErrors.length
      },

      getBadgeClasses(): string {
        switch (this.status) {
          case 'compliant':
            return 'bg-success-subtle text-success compliant-badge'
          case 'non_compliant':
            return 'bg-warning-subtle text-warning'
          case 'unknown':
            if (this.isNtiaAvailable) {
              return 'bg-info-subtle text-info ntia-checking'
            }
            return 'bg-secondary-subtle text-secondary'
          default:
            return ''
        }
      },

      getBadgeIconClass(): string {
        switch (this.status) {
          case 'compliant':
            return 'fas fa-award'
          case 'non_compliant':
            return 'fas fa-exclamation-triangle'
          case 'unknown':
            if (this.isNtiaAvailable) {
              return 'fas fa-clock fa-pulse'
            }
            return 'fas fa-lock'
          default:
            return ''
        }
      },

      getBadgeText(): string {
        switch (this.status) {
          case 'compliant':
            return 'Compliant'
          case 'non_compliant':
            return 'Not Compliant'
          case 'unknown':
            if (this.isNtiaAvailable) {
              return 'Checking...'
            }
            return 'Upgrade Required'
          default:
            return ''
        }
      },

      isBadgeClickable(): boolean {
        return this.status === 'non_compliant' || (this.status === 'unknown' && !this.isNtiaAvailable)
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

      initModal(element: HTMLElement): void {
        element.style.display = 'block'
        if (element.parentElement !== document.body) {
          document.body.appendChild(element)
        }
      },
    }
  })
}
