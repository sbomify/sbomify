<template>
  <div class="ntia-compliance-badge">
    <div
      v-if="status === 'compliant'"
      class="badge bg-success-subtle text-success d-flex align-items-center gap-1 compliant-badge"
      data-bs-toggle="tooltip"
      data-bs-placement="top"
      :title="getTooltipText()"
    >
      <i class="fas fa-award"></i>
      <span>Compliant</span>
    </div>

    <div
      v-else-if="status === 'partial'"
      class="badge bg-info-subtle text-info d-flex align-items-center gap-1"
      :class="{ 'interactive-badge': canShowDetails }"
      data-bs-toggle="tooltip"
      data-bs-placement="top"
      :title="getTooltipText()"
      @click="handleBadgeClick"
    >
      <i class="fas fa-info-circle"></i>
      <span>Partially Compliant</span>
    </div>

    <div
      v-else-if="status === 'non_compliant'"
      class="badge bg-warning-subtle text-warning d-flex align-items-center gap-1"
      :class="{ 'interactive-badge': canShowDetails }"
      data-bs-toggle="tooltip"
      data-bs-placement="top"
      :title="getTooltipText()"
      @click="handleBadgeClick"
    >
      <i class="fas fa-exclamation-triangle"></i>
      <span>Not Compliant</span>
    </div>

    <div
      v-else-if="status === 'unknown'"
      class="badge d-flex align-items-center gap-1"
      :class="getUnknownBadgeClasses()"
      data-bs-toggle="tooltip"
      data-bs-placement="top"
      :title="getTooltipText()"
      :style="getUnknownBadgeStyle()"
      @click="handleUnknownBadgeClick"
    >
      <i :class="getUnknownIconClass()"></i>
      <span>{{ getUnknownStatusText() }}</span>
    </div>

    <Teleport to="body">
      <div
        v-if="showDetailsModal"
        class="modal fade show"
        style="display: block; background-color: rgba(0,0,0,0.5);"
        tabindex="-1"
        @click.self="closeModal"
      >
        <div class="modal-dialog modal-xl modal-dialog-scrollable">
          <div class="modal-content">
            <div class="modal-header">
              <h5 class="modal-title d-flex align-items-center gap-2">
                <i
                  class="fas"
                  :class="status === 'non_compliant' ? 'fa-shield-exclamation text-warning' : 'fa-info-circle text-info'"
                ></i>
                <span>NTIA Compliance Overview</span>
              </h5>
              <button type="button" class="btn-close" @click="closeModal"></button>
            </div>
            <div class="modal-body">
              <div
                class="alert d-flex align-items-start"
                :class="status === 'non_compliant' ? 'alert-warning' : 'alert-info'"
              >
                <i
                  class="me-3 mt-1 flex-shrink-0"
                  :class="status === 'non_compliant' ? 'fas fa-exclamation-triangle' : 'fas fa-info-circle'"
                ></i>
                <div>
                  <strong v-if="status === 'non_compliant'">
                    This SBOM does not meet NTIA minimum elements requirements.
                  </strong>
                  <strong v-else>
                    This SBOM is partially compliant with NTIA minimum elements.
                  </strong>
                  <br>
                  Review the sections below for actionable guidance to bring this SBOM into compliance.
                </div>
              </div>

              <div v-if="summaryInfo" class="ntia-summary-card mb-4">
                <div class="row g-3">
                  <div class="col-12 col-md-3" v-if="summaryInfo.score !== null && summaryInfo.score !== undefined">
                    <div class="ntia-summary-stat">
                      <span class="label">Compliance Score</span>
                      <span class="value">{{ formatScore(summaryInfo.score) }}%</span>
                    </div>
                  </div>
                  <div class="col-12 col-md-3" v-if="checksSummary.total">
                    <div class="ntia-summary-stat">
                      <span class="label">Total Checks</span>
                      <span class="value">{{ checksSummary.total }}</span>
                    </div>
                  </div>
                  <div class="col-12 col-md-3">
                    <div class="ntia-summary-stat text-warning">
                      <span class="label">Failures</span>
                      <span class="value">{{ checksSummary.fail }}</span>
                    </div>
                  </div>
                  <div class="col-12 col-md-3">
                    <div class="ntia-summary-stat text-info">
                      <span class="label">Advisories</span>
                      <span class="value">{{ checksSummary.warning }}</span>
                    </div>
                  </div>
                  <div class="col-12" v-if="formattedCheckedAt">
                    <div class="ntia-summary-note">
                      Last evaluated {{ formattedCheckedAt }}
                    </div>
                  </div>
                </div>
              </div>

              <div v-if="sectionResults.length > 0" class="mb-4">
                <div class="section-header mb-3 d-flex align-items-center justify-content-between flex-wrap gap-2">
                  <h6 class="section-title d-flex align-items-center gap-2 mb-0">
                    <i class="fas fa-diagram-project"></i>
                    Section Overview
                  </h6>
                  <small class="text-muted" v-if="checksSummary.total">
                    {{ checksSummary.pass }} pass · {{ checksSummary.warning }} advisory · {{ checksSummary.fail }} fail
                  </small>
                </div>
                <div class="row g-3">
                  <div
                    v-for="section in sectionResults"
                    :key="section.name || section.title"
                    class="col-12 col-md-6"
                  >
                    <div class="ntia-section-card" :class="sectionCardClass(section.status)">
                      <div class="ntia-section-card__header">
                        <div>
                          <h6 class="mb-1 d-flex align-items-center gap-2">
                            <i :class="sectionIcon(section.status)"></i>
                            {{ section.title }}
                          </h6>
                          <p class="mb-0 text-muted">{{ section.summary }}</p>
                        </div>
                        <span class="badge" :class="sectionBadgeClass(section.status)">
                          {{ formatStatus(section.status) }}
                        </span>
                      </div>
                      <ul class="ntia-section-card__metrics list-unstyled mb-0">
                        <li v-if="section.metrics?.fail">
                          <i class="fas fa-exclamation-triangle text-warning me-2"></i>
                          {{ pluralize(section.metrics.fail, 'failure') }}
                        </li>
                        <li v-if="section.metrics?.warning">
                          <i class="fas fa-info-circle text-info me-2"></i>
                          {{ pluralize(section.metrics.warning, 'advisory', 'advisories') }}
                        </li>
                        <li v-if="section.metrics?.pass">
                          <i class="fas fa-check-circle text-success me-2"></i>
                          {{ pluralize(section.metrics.pass, 'pass') }}
                        </li>
                      </ul>
                    </div>
                  </div>
                </div>
              </div>

              <div v-if="complianceErrors.length > 0" class="mb-4">
                <div class="section-header mb-3">
                  <h6 class="section-title d-flex align-items-center gap-2">
                    <i class="fas fa-exclamation-circle"></i>
                    Issues Found ({{ complianceErrors.length }})
                  </h6>
                </div>
                <div class="ntia-issues-list">
                  <div
                    v-for="(error, index) in complianceErrors"
                    :key="`error-${index}`"
                    class="ntia-issue-item mb-3"
                  >
                    <div class="ntia-issue-header" @click="toggleItem(`error-${index}`)">
                      <div class="d-flex align-items-center gap-2 flex-wrap">
                        <i class="fas fa-exclamation-triangle text-warning"></i>
                        <span class="ntia-issue-field">{{ error.field }}:</span>
                        <span class="ntia-issue-message">{{ error.message }}</span>
                        <i
                          class="fas fa-chevron-down ms-auto transition-transform"
                          :class="{ 'rotate-180': isExpanded(`error-${index}`) }"
                        ></i>
                      </div>
                    </div>
                    <div v-if="isExpanded(`error-${index}`)" class="ntia-issue-body">
                      <div class="ntia-suggestion">
                        <i class="fas fa-lightbulb text-info me-2"></i>
                        <strong>Suggestion:</strong> {{ error.suggestion }}
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              <div v-if="complianceWarnings.length > 0" class="mb-4">
                <div class="section-header mb-3">
                  <h6 class="section-title text-info d-flex align-items-center gap-2">
                    <i class="fas fa-info-circle"></i>
                    Advisory Items ({{ complianceWarnings.length }})
                  </h6>
                </div>
                <div class="ntia-issues-list">
                  <div
                    v-for="(warning, index) in complianceWarnings"
                    :key="`warning-${index}`"
                    class="ntia-issue-item mb-3"
                  >
                    <div class="ntia-issue-header" @click="toggleItem(`warning-${index}`)">
                      <div class="d-flex align-items-center gap-2 flex-wrap">
                        <i class="fas fa-info-circle text-info"></i>
                        <span class="ntia-issue-field">{{ warning.title }}:</span>
                        <span class="ntia-issue-message">{{ warning.message }}</span>
                        <span class="badge" :class="checkStatusBadgeClass(warning.status)">
                          {{ checkStatusLabel(warning.status) }}
                        </span>
                        <i
                          class="fas fa-chevron-down ms-auto transition-transform"
                          :class="{ 'rotate-180': isExpanded(`warning-${index}`) }"
                        ></i>
                      </div>
                    </div>
                    <div v-if="isExpanded(`warning-${index}`)" class="ntia-issue-body">
                      <div class="ntia-suggestion" v-if="warning.suggestion">
                        <i class="fas fa-lightbulb text-info me-2"></i>
                        <strong>Suggestion:</strong> {{ warning.suggestion }}
                      </div>
                      <div v-if="warning.affected && warning.affected.length" class="ntia-suggestion mt-2">
                        <strong>Affected:</strong> {{ warning.affected.join(', ') }}
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              <div class="alert alert-info">
                <div class="section-header-info mb-3">
                  <h6 class="section-title-info d-flex align-items-center gap-2">
                    <i class="fas fa-lightbulb"></i>
                    How to Improve
                  </h6>
                </div>
                <ul class="mb-0 fix-suggestions">
                  <li class="mb-2">
                    <strong>Use our <a href="https://github.com/sbomify/github-action" target="_blank" rel="noopener" class="text-decoration-none">GitHub Actions module</a></strong> for automated SBOM generation.
                  </li>
                  <li class="mb-2">
                    <strong>Ensure your SBOM includes all 7 NTIA minimum elements:</strong>
                    <ul class="mt-2 ntia-elements-list">
                      <li>Supplier name</li>
                      <li>Component name</li>
                      <li>Version of the component</li>
                      <li>Unique identifiers (PURL, CPE, etc.)</li>
                      <li>Dependency relationships</li>
                      <li>Author of SBOM data</li>
                      <li>Timestamp</li>
                    </ul>
                  </li>
                  <li>
                    <strong>Validate your SBOM</strong> before uploading using SBOM validation tools.
                  </li>
                </ul>
              </div>
            </div>
            <div class="modal-footer">
              <button type="button" class="btn btn-secondary" @click="closeModal">
                Close
              </button>
              <a
                href="https://github.com/sbomify/github-action"
                target="_blank"
                rel="noopener"
                class="btn btn-primary"
              >
                <i class="fab fa-github me-2"></i>
                View GitHub Action
              </a>
            </div>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'

interface ComplianceError {
  field: string
  message: string
  suggestion?: string
}

interface NtiaCheck {
  element?: string
  title: string
  status?: string | null
  message: string
  suggestion?: string | null
  affected?: string[]
}

interface NtiaSectionMetrics {
  total?: number
  pass?: number
  warning?: number
  fail?: number
  unknown?: number
}

interface NtiaSection {
  name?: string
  title: string
  summary: string
  status?: string | null
  metrics?: NtiaSectionMetrics
  checks?: NtiaCheck[]
}

interface NtiaSummary {
  errors?: number
  warnings?: number
  status?: string
  score?: number | null
  checks?: NtiaSectionMetrics & { total?: number }
  sections?: Record<string, { status?: string; metrics?: NtiaSectionMetrics; title?: string; summary?: string }>
}

interface ComplianceDetails {
  is_compliant?: boolean
  status?: string
  error_count?: number
  warning_count?: number
  errors?: ComplianceError[]
  warnings?: NtiaCheck[]
  sections?: NtiaSection[]
  summary?: NtiaSummary
  checked_at?: string | null
  format?: string
}

interface Props {
  status: 'compliant' | 'partial' | 'non_compliant' | 'unknown'
  complianceDetails?: ComplianceDetails | string | null
  isPublicView?: boolean
  teamBillingPlan?: string
  teamKey?: string
}

const props = withDefaults(defineProps<Props>(), {
  complianceDetails: null,
  isPublicView: false,
  teamBillingPlan: 'community',
  teamKey: ''
})

const showDetailsModal = ref(false)
const expandedItems = ref<string[]>([])

const normalizedDetails = computed<ComplianceDetails>(() => {
  const details = props.complianceDetails
  if (!details) {
    return {}
  }

  if (typeof details === 'string') {
    try {
      return JSON.parse(details) as ComplianceDetails
    } catch (error) {
      console.warn('[NTIAComplianceBadge] Failed to parse complianceDetails prop', error)
      return {}
    }
  }

  return details
})

const complianceErrors = computed<ComplianceError[]>(() => normalizedDetails.value.errors || [])
const complianceWarnings = computed<NtiaCheck[]>(() => normalizedDetails.value.warnings || [])
const sectionResults = computed<NtiaSection[]>(() => normalizedDetails.value.sections || [])
const summaryInfo = computed<NtiaSummary | null>(() => normalizedDetails.value.summary || null)

const checksSummary = computed(() => {
  const summaryChecks = summaryInfo.value?.checks
  if (summaryChecks) {
    return {
      total: summaryChecks.total ?? 0,
      pass: summaryChecks.pass ?? 0,
      warning: summaryChecks.warning ?? 0,
      fail: summaryChecks.fail ?? 0,
      unknown: summaryChecks.unknown ?? 0
    }
  }

  return {
    total: complianceErrors.value.length + complianceWarnings.value.length,
    pass: 0,
    warning: complianceWarnings.value.length,
    fail: complianceErrors.value.length,
    unknown: 0
  }
})

const errorCount = computed(() => {
  if (typeof normalizedDetails.value.error_count === 'number') {
    return normalizedDetails.value.error_count
  }
  if (summaryInfo.value?.errors !== undefined) {
    return summaryInfo.value.errors ?? 0
  }
  return complianceErrors.value.length
})

const warningCount = computed(() => {
  if (typeof normalizedDetails.value.warning_count === 'number') {
    return normalizedDetails.value.warning_count
  }
  if (summaryInfo.value?.warnings !== undefined) {
    return summaryInfo.value.warnings ?? 0
  }
  return complianceWarnings.value.length
})

const checkedAt = computed(() => normalizedDetails.value.checked_at || null)

const formattedCheckedAt = computed(() => {
  if (!checkedAt.value) {
    return null
  }
  const parsed = new Date(checkedAt.value)
  if (Number.isNaN(parsed.getTime())) {
    return null
  }
  return parsed.toLocaleString()
})

const canShowDetails = computed(() => !props.isPublicView && ['non_compliant', 'partial'].includes(props.status))

const handleBadgeClick = (): void => {
  if (canShowDetails.value) {
    showDetailsModal.value = true
  }
}

const toggleItem = (key: string): void => {
  if (!key) {
    return
  }

  const currentIndex = expandedItems.value.indexOf(key)
  if (currentIndex > -1) {
    expandedItems.value.splice(currentIndex, 1)
  } else {
    expandedItems.value.push(key)
  }
}

const isExpanded = (key: string): boolean => expandedItems.value.includes(key)

const isNtiaAvailable = (): boolean =>
  props.teamBillingPlan === 'business' || props.teamBillingPlan === 'enterprise'

const getUnknownBadgeClasses = (): string =>
  isNtiaAvailable() ? 'bg-info-subtle text-info ntia-checking' : 'bg-secondary-subtle text-secondary'

const getUnknownBadgeStyle = (): string => (isNtiaAvailable() ? '' : 'cursor: pointer;')

const getUnknownIconClass = (): string => (isNtiaAvailable() ? 'fas fa-clock fa-pulse' : 'fas fa-lock')

const getUnknownStatusText = (): string => (isNtiaAvailable() ? 'Checking...' : 'Upgrade Required')

const handleUnknownBadgeClick = (): void => {
  if (!isNtiaAvailable()) {
    const upgradePath = props.teamKey ? `/billing/select-plan/${props.teamKey}` : '/billing/select-plan/'
    window.location.href = upgradePath
  }
}

const getTooltipText = (): string => {
  switch (props.status) {
    case 'compliant':
      return 'This SBOM meets all NTIA minimum elements requirements.'
    case 'partial': {
      const warnings = warningCount.value
      if (warnings > 0) {
        return `This SBOM has ${warnings} NTIA advisory item${warnings !== 1 ? 's' : ''}. Click for guidance.`
      }
      return 'This SBOM is partially compliant with NTIA minimum elements.'
    }
    case 'non_compliant': {
      const errors = errorCount.value
      return `This SBOM has ${errors} NTIA compliance issue${errors !== 1 ? 's' : ''}. Click for details.`
    }
    case 'unknown':
      if (isNtiaAvailable()) {
        return 'NTIA compliance check is being performed in the background. This usually takes a few minutes to complete.'
      }
      return 'NTIA Minimum Elements compliance is available with Business and Enterprise plans. Upgrade to unlock this feature.'
    default:
      return 'NTIA compliance status unknown.'
  }
}

const formatStatus = (status?: string | null): string => {
  switch (status) {
    case 'pass':
      return 'Pass'
    case 'warning':
      return 'Advisory'
    case 'fail':
      return 'Failure'
    default:
      return 'Unknown'
  }
}

const sectionIcon = (status?: string | null): string => {
  switch (status) {
    case 'fail':
      return 'fas fa-circle-xmark text-warning'
    case 'warning':
      return 'fas fa-circle-exclamation text-info'
    case 'pass':
      return 'fas fa-circle-check text-success'
    default:
      return 'fas fa-circle text-secondary'
  }
}

const sectionBadgeClass = (status?: string | null): string => {
  switch (status) {
    case 'fail':
      return 'bg-warning-subtle text-warning'
    case 'warning':
      return 'bg-info-subtle text-info'
    case 'pass':
      return 'bg-success-subtle text-success'
    default:
      return 'bg-secondary-subtle text-secondary'
  }
}

const sectionCardClass = (status?: string | null): string => {
  switch (status) {
    case 'fail':
      return 'ntia-section-card--fail'
    case 'warning':
      return 'ntia-section-card--warning'
    case 'pass':
      return 'ntia-section-card--pass'
    default:
      return 'ntia-section-card--unknown'
  }
}

const checkStatusLabel = (status?: string | null): string => {
  switch (status) {
    case 'fail':
      return 'Failure'
    case 'warning':
      return 'Advisory'
    case 'pass':
      return 'Pass'
    default:
      return 'Unknown'
  }
}

const checkStatusBadgeClass = (status?: string | null): string => {
  switch (status) {
    case 'fail':
      return 'bg-warning-subtle text-warning border border-warning-subtle'
    case 'warning':
      return 'bg-info-subtle text-info border border-info-subtle'
    case 'pass':
      return 'bg-success-subtle text-success border border-success-subtle'
    default:
      return 'bg-secondary-subtle text-secondary border border-secondary-subtle'
  }
}

const formatScore = (score?: number | null): string => {
  if (score === null || score === undefined) {
    return '0.0'
  }
  const rounded = Number(score)
  if (Number.isNaN(rounded)) {
    return '0.0'
  }
  return rounded % 1 === 0 ? rounded.toFixed(0) : rounded.toFixed(1)
}

const pluralize = (count: number | undefined, singular: string, plural?: string): string => {
  const safeCount = Number(count) || 0
  const label = safeCount === 1 ? singular : plural || `${singular}s`
  return `${safeCount} ${label}`
}

const closeModal = (): void => {
  showDetailsModal.value = false
  expandedItems.value = []
}

onMounted(() => {
  const tooltipTriggerList = document.querySelectorAll('[data-bs-toggle="tooltip"]')
  if (typeof window !== 'undefined' && window.bootstrap?.Tooltip) {
    Array.from(tooltipTriggerList).forEach(tooltipTriggerEl => {
      new window.bootstrap!.Tooltip(tooltipTriggerEl)
    })
  }
})

onUnmounted(() => {
  const tooltips = document.querySelectorAll('.tooltip')
  tooltips.forEach(tooltip => tooltip.remove())
})
</script>

<style scoped>
.ntia-compliance-badge .badge {
  font-size: 0.75rem;
  font-weight: 600;
  padding: 0.375rem 0.75rem;
  border-radius: 0.375rem;
  border: 1px solid;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}

.interactive-badge {
  cursor: pointer;
}

.interactive-badge:hover {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.12);
}

.ntia-compliance-badge .badge.bg-success-subtle {
  border-color: var(--bs-success-border-subtle);
}

.ntia-compliance-badge .badge.bg-warning-subtle {
  border-color: var(--bs-warning-border-subtle);
}

.ntia-compliance-badge .badge.bg-secondary-subtle {
  border-color: var(--bs-secondary-border-subtle);
}

.ntia-compliance-badge .badge.bg-info-subtle {
  border-color: var(--bs-info-border-subtle);
}

.ntia-compliance-badge .badge i {
  font-size: 0.875rem;
}

.ntia-compliance-badge .compliant-badge {
  background: linear-gradient(135deg, #d4edda 0%, #c3e6cb 100%) !important;
  border-color: #198754 !important;
  position: relative;
  overflow: visible;
}

.ntia-compliance-badge .compliant-badge i {
  color: #ffc107;
  font-size: 1rem;
  filter: drop-shadow(0 1px 2px rgba(255, 193, 7, 0.3));
}

.ntia-compliance-badge .compliant-badge:before {
  content: "";
  position: absolute;
  top: -2px;
  left: -2px;
  right: -2px;
  bottom: -2px;
  background: linear-gradient(135deg, rgba(255, 193, 7, 0.15) 0%, rgba(25, 135, 84, 0.15) 100%);
  border-radius: 0.5rem;
  z-index: -1;
}

.ntia-summary-card {
  background: linear-gradient(135deg, #ffffff 0%, #f8fafc 100%);
  border: 1px solid #e2e8f0;
  border-radius: 0.75rem;
  padding: 1.5rem 1.75rem;
  box-shadow: 0 4px 8px rgba(15, 23, 42, 0.05);
}

.ntia-summary-stat {
  background: #ffffff;
  border-radius: 0.75rem;
  border: 1px solid #e2e8f0;
  padding: 1rem;
  text-align: center;
  min-height: 100%;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  justify-content: center;
  box-shadow: 0 2px 6px rgba(15, 23, 42, 0.05);
}

.ntia-summary-stat .label {
  font-size: 0.75rem;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: #64748b;
  font-weight: 600;
}

.ntia-summary-stat .value {
  font-size: 1.5rem;
  font-weight: 700;
  color: #0f172a;
}

.ntia-summary-note {
  font-size: 0.85rem;
  color: #475569;
  background: rgba(99, 102, 241, 0.08);
  border-radius: 0.5rem;
  padding: 0.75rem 1rem;
  border: 1px solid rgba(99, 102, 241, 0.12);
}

.ntia-section-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 0.75rem;
  padding: 1.25rem 1.5rem;
  min-height: 100%;
  box-shadow: 0 3px 8px rgba(15, 23, 42, 0.05);
  transition: border-color 0.2s ease, box-shadow 0.2s ease, transform 0.2s ease;
}

.ntia-section-card--fail {
  border-left: 4px solid var(--bs-warning);
}

.ntia-section-card--warning {
  border-left: 4px solid var(--bs-info);
}

.ntia-section-card--pass {
  border-left: 4px solid var(--bs-success);
}

.ntia-section-card--unknown {
  border-left: 4px solid var(--bs-secondary);
}

.ntia-section-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 16px rgba(15, 23, 42, 0.12);
}

.ntia-section-card__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 0.75rem;
}

.ntia-section-card__header h6 {
  font-size: 1rem;
  font-weight: 700;
  color: #0f172a;
}

.ntia-section-card__header p {
  font-size: 0.85rem;
  color: #64748b;
}

.ntia-section-card__metrics li {
  font-size: 0.85rem;
  color: #334155;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.35rem;
}

.ntia-section-card__metrics li:last-child {
  margin-bottom: 0;
}

.transition-transform {
  transition: transform 0.2s ease;
}

.rotate-180 {
  transform: rotate(180deg);
}

.ntia-issues-list {
  background-color: #f8f9fa;
  border-radius: 0.75rem;
  padding: 1rem;
  border: 1px solid #e9ecef;
}

.ntia-issue-item {
  background: linear-gradient(135deg, #ffffff 0%, #fdfdfd 100%);
  border: 1px solid #e9ecef;
  border-radius: 0.75rem;
  overflow: hidden;
  transition: all 0.2s ease-in-out;
  box-shadow: 0 2px 6px rgba(148, 163, 184, 0.2);
}

.ntia-issue-item + .ntia-issue-item {
  margin-top: 0.75rem;
}

.ntia-issue-item:hover {
  transform: translateY(-1px);
  box-shadow: 0 6px 14px rgba(148, 163, 184, 0.25);
  border-color: #ffd24c;
}

.ntia-issue-header {
  padding: 1.1rem 1.25rem;
  cursor: pointer;
  user-select: none;
  background: linear-gradient(135deg, #fff9db 0%, #fff4bf 100%);
  border-bottom: 1px solid #ffe69c;
  transition: background 0.2s ease-in-out;
}

.ntia-issue-header:hover {
  background: linear-gradient(135deg, #fff4bf 0%, #ffe69c 100%);
}

.ntia-issue-field {
  font-weight: 700;
  color: #d63384;
  font-size: 0.95rem;
  text-transform: capitalize;
}

.ntia-issue-message {
  color: #334155;
  font-size: 0.9rem;
  line-height: 1.4;
  flex: 1;
  min-width: 0;
}

.ntia-issue-body {
  padding: 1.1rem 1.25rem;
  background-color: #ffffff;
}

.ntia-suggestion {
  background: linear-gradient(135deg, #e8f4fd 0%, #f4f8ff 100%);
  padding: 1rem;
  border-radius: 0.65rem;
  border-left: 4px solid #0d6efd;
  font-size: 0.9rem;
  line-height: 1.5;
  box-shadow: 0 2px 6px rgba(13, 110, 253, 0.12);
}

.section-header {
  background: linear-gradient(135deg, #ffffff 0%, #f8fafc 100%);
  padding: 1rem 1.25rem;
  border-radius: 0.75rem;
  border: 1px solid #e2e8f0;
  box-shadow: 0 2px 4px rgba(15, 23, 42, 0.05);
}

.section-title {
  margin: 0;
  font-weight: 700;
  color: #b91c1c;
  font-size: 1rem;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.section-title i {
  color: #f97316;
}

.section-header-info {
  background: linear-gradient(135deg, #e0f2fe 0%, #eff6ff 100%);
  padding: 1.25rem 1.5rem;
  border-radius: 0.75rem;
  border: 1px solid rgba(14, 165, 233, 0.2);
  box-shadow: 0 2px 6px rgba(14, 165, 233, 0.15);
}

.section-title-info {
  margin: 0;
  font-weight: 700;
  color: #0ea5e9;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.fix-suggestions {
  list-style: none;
  padding: 0;
  margin: 0;
}

.fix-suggestions li {
  color: #0f172a;
  font-size: 0.92rem;
  line-height: 1.5;
}

.ntia-elements-list {
  list-style: disc;
  padding-left: 1.5rem;
  margin-bottom: 0;
  color: #0f172a;
  font-size: 0.9rem;
}

.ntia-elements-list li {
  color: #495057;
  font-size: 0.95rem;
  margin-bottom: 0.5rem;
  position: relative;
  padding-left: 1.75rem;
  line-height: 1.5;
}

.ntia-elements-list li:last-child {
  margin-bottom: 0;
}

.ntia-elements-list li:before {
  content: "✓";
  position: absolute;
  left: 0;
  top: 0.1rem;
  color: #198754;
  font-weight: bold;
  font-size: 1rem;
  width: 1.25rem;
  text-align: center;
  z-index: 1;
}

.modal {
  z-index: 1060;
}

.modal-backdrop {
  z-index: 1055;
}

.modal-lg {
  max-width: 850px;
}

.modal-content {
  border: none;
  border-radius: 1rem;
  box-shadow: 0 10px 40px rgba(0, 0, 0, 0.2);
}

.modal-header {
  background: linear-gradient(135deg, #fff 0%, #f8f9fa 100%);
  border-bottom: 1px solid #e9ecef;
  border-radius: 1rem 1rem 0 0;
  padding: 1.5rem;
}

.modal-title {
  font-weight: 700;
  font-size: 1.25rem;
  color: #495057;
}

.modal-body {
  padding: 2rem;
  background-color: #fff;
}

.modal-footer {
  background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);
  border-top: 1px solid #e9ecef;
  border-radius: 0 0 1rem 1rem;
  padding: 1.5rem;
}

.btn-primary {
  background: linear-gradient(135deg, #0d6efd 0%, #0b5ed7 100%);
  border: none;
  border-radius: 0.5rem;
  padding: 0.75rem 1.5rem;
  font-weight: 600;
  transition: all 0.2s ease;
  box-shadow: 0 2px 4px rgba(13, 110, 253, 0.3);
}

.btn-primary:hover {
  transform: translateY(-1px);
  box-shadow: 0 4px 8px rgba(13, 110, 253, 0.4);
}

.btn-secondary {
  background: linear-gradient(135deg, #6c757d 0%, #5a6268 100%);
  border: none;
  border-radius: 0.5rem;
  padding: 0.75rem 1.5rem;
  font-weight: 600;
  transition: all 0.2s ease;
}

.ntia-checking {
  opacity: 0.9;
  animation: subtle-pulse 2s infinite ease-in-out;
}

@keyframes subtle-pulse {
  0%, 100% {
    opacity: 0.9;
  }
  50% {
    opacity: 0.7;
  }
}

@media (max-width: 768px) {
  .ntia-compliance-badge .badge {
    width: 100%;
    justify-content: center;
  }

  .ntia-section-card {
    padding: 1rem 1.25rem;
  }

  .ntia-section-card__header {
    flex-direction: column;
    align-items: flex-start;
  }

  .ntia-summary-card {
    padding: 1.25rem;
  }
}
</style>
