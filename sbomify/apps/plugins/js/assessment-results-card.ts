import Alpine from 'alpinejs'

interface FindingSummary {
  total_findings: number
  pass_count: number
  fail_count: number
  warning_count: number
  info_count: number
  error_count: number
}

interface Finding {
  id: string
  title: string
  description: string
  status: 'pass' | 'fail' | 'warning' | 'info' | 'error'
  severity?: string
  remediation?: string
  metadata?: Record<string, unknown>
}

interface AssessmentResult {
  plugin_name: string
  plugin_version: string
  category: string
  assessed_at: string
  summary: FindingSummary
  findings: Finding[]
  metadata?: {
    standard_name?: string
    standard_version?: string
    standard_url?: string
    [key: string]: unknown
  }
}

interface AssessmentRun {
  id: string
  sbom_id: string
  plugin_name: string
  plugin_version: string
  plugin_display_name?: string
  category: string
  run_reason: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  started_at?: string
  completed_at?: string
  error_message?: string
  result?: AssessmentResult
  created_at: string
}

interface AssessmentRunsData {
  sbom_id: string
  status_summary: {
    overall_status: string
    total_assessments: number
    passing_count: number
    failing_count: number
    pending_count: number
    in_progress_count: number
  }
  latest_runs: AssessmentRun[]
  all_runs: AssessmentRun[]
}

export function registerAssessmentResultsCard() {
  Alpine.data('assessmentResultsCard', (sbomId: string, runsDataJson: string) => {
    const runsData: AssessmentRunsData = JSON.parse(runsDataJson || '{}')

    // Helper to determine run status category
    function getRunStatusCategory(run: AssessmentRun): 'failed' | 'passed' | 'pending' {
      if (run.status === 'completed') {
        const summary = run.result?.summary
        if (summary && (summary.fail_count > 0 || summary.error_count > 0)) {
          return 'failed'
        }
        return 'passed'
      }
      if (run.status === 'failed') {
        return 'failed'
      }
      // pending or running
      return 'pending'
    }

    // Group runs by status
    function groupRunsByStatus(runs: AssessmentRun[]): {
      failed: AssessmentRun[]
      passed: AssessmentRun[]
      pending: AssessmentRun[]
    } {
      const groups = {
        failed: [] as AssessmentRun[],
        passed: [] as AssessmentRun[],
        pending: [] as AssessmentRun[],
      }
      for (const run of runs) {
        const category = getRunStatusCategory(run)
        groups[category].push(run)
      }
      return groups
    }

    // Store bound handler for cleanup
    let hashChangeHandler: (() => void) | null = null

    return {
      sbomId,
      expandedPluginId: null as string | null,

      init() {
        // Handle anchor links on page load
        this.handleAnchorLink()
        // Listen for hash changes - store handler for cleanup
        hashChangeHandler = () => this.handleAnchorLink()
        window.addEventListener('hashchange', hashChangeHandler)
      },

      destroy() {
        // Clean up when Alpine destroys this component
        if (hashChangeHandler) {
          window.removeEventListener('hashchange', hashChangeHandler)
          hashChangeHandler = null
        }
      },

      handleAnchorLink() {
        const hash = window.location.hash
        // Clear expanded state if no hash
        if (!hash) {
          this.expandedPluginId = null
          return
        }

        if (hash.startsWith('#plugin-')) {
          const pluginName = hash.replace('#plugin-', '')
          // Find the run with this plugin name
          const run = this.latestRuns.find(r => r.plugin_name === pluginName)
          if (run) {
            this.expandedPluginId = run.id
            // Scroll to the element after a short delay to ensure it's rendered
            setTimeout(() => {
              const element = document.getElementById(`plugin-${pluginName}`)
              if (element) {
                element.scrollIntoView({ behavior: 'smooth', block: 'start' })
              }
            }, 100)
          }
        } else if (hash === '#assessment-results') {
          // Clear expanded state when navigating to section header
          this.expandedPluginId = null
          setTimeout(() => {
            const element = document.getElementById('assessment-results')
            if (element) {
              element.scrollIntoView({ behavior: 'smooth', block: 'start' })
            }
          }, 100)
        } else {
          // Clear expanded state when navigating to other anchors
          this.expandedPluginId = null
        }
      },

      isExpanded(runId: string): boolean {
        return this.expandedPluginId === runId
      },

      toggleExpanded(runId: string) {
        if (this.expandedPluginId === runId) {
          this.expandedPluginId = null
        } else {
          this.expandedPluginId = runId
        }
      },

      get statusSummary() {
        return runsData.status_summary || {
          overall_status: 'no_assessments',
          total_assessments: 0,
          passing_count: 0,
          failing_count: 0,
          pending_count: 0,
          in_progress_count: 0,
        }
      },

      get latestRuns(): AssessmentRun[] {
        return runsData.latest_runs || []
      },

      get allRuns(): AssessmentRun[] {
        return runsData.all_runs || []
      },

      // Grouped runs by status (failed first, then passed, then pending)
      get groupedRuns(): { failed: AssessmentRun[], passed: AssessmentRun[], pending: AssessmentRun[] } {
        return groupRunsByStatus(this.latestRuns)
      },

      get failedRuns(): AssessmentRun[] {
        return this.groupedRuns.failed
      },

      get passedRuns(): AssessmentRun[] {
        return this.groupedRuns.passed
      },

      get pendingRuns(): AssessmentRun[] {
        return this.groupedRuns.pending
      },

      get totalAssessments(): number {
        return this.statusSummary.total_assessments
      },

      get passingCount(): number {
        return this.statusSummary.passing_count
      },

      get failingCount(): number {
        return this.statusSummary.failing_count
      },

      get pendingCount(): number {
        return this.statusSummary.pending_count + this.statusSummary.in_progress_count
      },

      getOverallStatusBadgeClass(): string {
        switch (this.statusSummary.overall_status) {
          case 'all_pass':
            return 'bg-success-subtle text-success'
          case 'has_failures':
            return 'bg-warning-subtle text-warning'
          case 'pending':
          case 'in_progress':
            return 'bg-info-subtle text-info'
          default:
            return 'bg-secondary-subtle text-secondary'
        }
      },

      getOverallStatusIconClass(): string {
        switch (this.statusSummary.overall_status) {
          case 'all_pass':
            return 'fas fa-check-circle me-1'
          case 'has_failures':
            return 'fas fa-exclamation-triangle me-1'
          case 'pending':
          case 'in_progress':
            return 'fas fa-clock fa-pulse me-1'
          default:
            return 'fas fa-clock me-1'
        }
      },

      getOverallStatusText(): string {
        switch (this.statusSummary.overall_status) {
          case 'all_pass':
            return 'All Passed'
          case 'has_failures':
            return 'Issues Found'
          case 'pending':
          case 'in_progress':
            return 'Processing'
          default:
            return 'No Results'
        }
      },

      getRunStatusBadgeClass(run: AssessmentRun): string {
        if (run.status === 'completed') {
          const summary = run.result?.summary
          if (summary && (summary.fail_count > 0 || summary.error_count > 0)) {
            return 'bg-warning-subtle text-warning'
          }
          return 'bg-success-subtle text-success'
        }
        if (run.status === 'failed') {
          return 'bg-danger-subtle text-danger'
        }
        if (run.status === 'running' || run.status === 'pending') {
          return 'bg-info-subtle text-info'
        }
        return 'bg-secondary-subtle text-secondary'
      },

      getRunStatusText(run: AssessmentRun): string {
        if (run.status === 'completed') {
          const summary = run.result?.summary
          if (summary && (summary.fail_count > 0 || summary.error_count > 0)) {
            return `${summary.fail_count + summary.error_count} Issue${(summary.fail_count + summary.error_count) > 1 ? 's' : ''}`
          }
          return 'Passed'
        }
        if (run.status === 'failed') {
          return 'Error'
        }
        if (run.status === 'running') {
          return 'Running'
        }
        if (run.status === 'pending') {
          return 'Pending'
        }
        return run.status
      },

      getFindingBorderClass(status: string): string {
        switch (status) {
          case 'pass':
            return 'border-success'
          case 'fail':
            return 'border-warning'
          case 'warning':
            return 'border-info'
          case 'error':
            return 'border-danger'
          default:
            return 'border-secondary'
        }
      },

      getFindingIconClass(status: string): string {
        switch (status) {
          case 'pass':
            return 'text-success'
          case 'fail':
            return 'text-warning'
          case 'warning':
            return 'text-info'
          case 'error':
            return 'text-danger'
          default:
            return 'text-secondary'
        }
      },

      getFindingIcon(status: string): string {
        switch (status) {
          case 'pass':
            return 'fas fa-check-circle'
          case 'fail':
            return 'fas fa-times-circle'
          case 'warning':
            return 'fas fa-exclamation-circle'
          case 'error':
            return 'fas fa-exclamation-triangle'
          default:
            return 'fas fa-info-circle'
        }
      },

      formatDate(dateStr: string | undefined): string {
        if (!dateStr) return '-'
        const date = new Date(dateStr)
        return date.toLocaleDateString('en-US', {
          month: 'short',
          day: 'numeric',
          year: 'numeric',
          hour: '2-digit',
          minute: '2-digit',
        })
      },

      formatRunReason(reason: string): string {
        const reasons: Record<string, string> = {
          'on_upload': 'Upload',
          'manual': 'Manual',
          'scheduled': 'Scheduled',
          'config_change': 'Config Change',
          'migration': 'Migration',
        }
        return reasons[reason] || reason
      },
    }
  })
}

