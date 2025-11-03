<template>
  <div
    v-if="!isPublicView"
    class="ntia-assistant-card"
  >
    <header class="ntia-assistant-card__header">
      <div class="ntia-assistant-card__title">
        <i class="fas fa-compass me-2 text-primary"></i>
        <div>
          <h2>NTIA Compliance Assistant</h2>
          <p class="mb-0 text-muted">
            Follow the guided steps to address outstanding NTIA minimum element requirements.
          </p>
        </div>
      </div>
      <span class="badge" :class="statusBadgeClass">
        {{ formatStatus(status) }}
      </span>
    </header>

    <section class="ntia-assistant-card__summary" v-if="wizardSteps.length">
      <div class="summary-tile">
        <span class="summary-label">Checks</span>
        <span class="summary-value">{{ checksSummary.total }}</span>
      </div>
      <div class="summary-tile summary-tile--success">
        <span class="summary-label">Pass</span>
        <span class="summary-value">{{ checksSummary.pass }}</span>
      </div>
      <div class="summary-tile summary-tile--warning">
        <span class="summary-label">Advisories</span>
        <span class="summary-value">{{ checksSummary.warning }}</span>
      </div>
      <div class="summary-tile summary-tile--error">
        <span class="summary-label">Failures</span>
        <span class="summary-value">{{ checksSummary.fail }}</span>
      </div>
    </section>

    <div v-else class="ntia-assistant-card__empty">
      <i class="fas fa-clipboard-list mb-3"></i>
      <p class="mb-2">No NTIA compliance data is available yet.</p>
      <p class="text-muted mb-3">
        Run the NTIA compliance check to generate an action plan for this SBOM.
      </p>
      <a
        href="https://github.com/sbomify/github-action"
        target="_blank"
        rel="noopener"
        class="btn btn-outline-primary btn-sm"
      >
        Learn how to generate compliant SBOMs
      </a>
    </div>

    <section v-if="wizardSteps.length" class="ntia-assistant-card__body">
      <nav class="ntia-stepper" aria-label="NTIA compliance steps">
        <button
          v-for="(step, index) in wizardSteps"
          :key="step.id || index"
          type="button"
          class="ntia-stepper__item"
          :class="stepperItemClass(index, step.status)"
          @click="activeIndex = index"
        >
          <span class="ntia-stepper__indicator">
            <i :class="stepStatusIcon(step.status)"></i>
          </span>
          <span class="ntia-stepper__title">{{ step.title }}</span>
        </button>
      </nav>

      <article class="ntia-step-card" v-if="currentStep">
        <header class="ntia-step-card__header">
          <div>
            <h3 class="ntia-step-card__title">{{ currentStep.title }}</h3>
            <p class="ntia-step-card__summary text-muted mb-0">
              {{ currentStep.summary || 'Review the checks for this NTIA area.' }}
            </p>
          </div>
          <span class="badge" :class="stepStatusBadgeClass(currentStep.status)">
            {{ formatStatus(currentStep.status) }}
          </span>
        </header>

        <div class="ntia-step-card__content">
          <div
            v-for="(check, index) in currentStep.checks"
            :key="`${currentStep.id}-check-${index}`"
            class="ntia-check-item"
            :class="checkClass(check.status)"
          >
            <div class="ntia-check-item__meta">
              <span class="ntia-check-item__icon">
                <i :class="checkStatusIcon(check.status)"></i>
              </span>
              <div>
                <h4 class="ntia-check-item__title">
                  {{ check.title || check.element || 'Requirement' }}
                </h4>
                <p class="ntia-check-item__message mb-1">{{ check.message }}</p>
                <p v-if="check.suggestion" class="ntia-check-item__suggestion">
                  <i class="fas fa-lightbulb me-2"></i>
                  {{ check.suggestion }}
                </p>
                <p v-if="check.affected?.length" class="ntia-check-item__affected">
                  <strong>Affected:</strong> {{ check.affected.join(', ') }}
                </p>
              </div>
            </div>
          </div>
        </div>

        <footer class="ntia-step-card__footer">
          <button
            type="button"
            class="btn btn-outline-secondary btn-sm"
            :disabled="activeIndex === 0"
            @click="goToPreviousStep"
          >
            <i class="fas fa-arrow-left me-1"></i>
            Previous
          </button>
          <div class="flex-grow-1 text-center">
            <small class="text-muted">
              Step {{ activeIndex + 1 }} of {{ wizardSteps.length }}
            </small>
          </div>
          <button
            type="button"
            class="btn btn-primary btn-sm"
            :disabled="activeIndex === wizardSteps.length - 1"
            @click="goToNextStep"
          >
            Next
            <i class="fas fa-arrow-right ms-1"></i>
          </button>
        </footer>
      </article>
    </section>

    <section v-if="actionableChecks.length" class="ntia-assistant-card__actions">
      <header class="ntia-assistant-card__actions-header">
        <h3>
          <i class="fas fa-tasks me-2 text-warning"></i>
          Suggested Remediation Actions
        </h3>
        <p class="mb-0 text-muted">
          Focus on the items below to move toward full NTIA compliance.
        </p>
      </header>
      <ul class="ntia-action-list">
        <li
          v-for="(item, index) in actionableChecks"
          :key="`action-${index}`"
          class="ntia-action-list__item"
        >
          <div class="ntia-action-list__icon">
            <i :class="checkStatusIcon(item.status)"></i>
          </div>
          <div class="ntia-action-list__body">
            <h4>{{ item.title || item.element || 'Requirement' }}</h4>
            <p class="mb-1">{{ item.suggestion || item.message }}</p>
            <p v-if="item.affected?.length" class="mb-0 text-muted">
              Affected components: {{ item.affected.join(', ') }}
            </p>
          </div>
        </li>
      </ul>

      <div class="ntia-assistant-card__resources">
        <h4 class="mb-2 text-primary">
          <i class="fas fa-book-open me-2"></i>
          Helpful Resources
        </h4>
        <ul class="ntia-resource-links">
          <li>
            <a href="https://www.ntia.gov/files/ntia/publications/sbom_minimum_elements_report.pdf" target="_blank" rel="noopener">
              NTIA Minimum Elements report
            </a>
          </li>
          <li>
            <a href="https://github.com/sbomify/github-action" target="_blank" rel="noopener">
              SBOMify GitHub Actions workflow
            </a>
          </li>
          <li>
            <a href="https://www.cisa.gov/sites/default/files/2024-04/cisa-sbom-sharing-guidance.pdf" target="_blank" rel="noopener">
              CISA SBOM sharing guidance
            </a>
          </li>
        </ul>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'

interface NtiaCheck {
  element?: string
  title?: string
  status?: string | null
  message: string
  suggestion?: string | null
  affected?: string[]
}

interface NtiaSection {
  id?: string
  name?: string
  title: string
  summary?: string
  status?: string | null
  checks?: NtiaCheck[]
}

interface NtiaSummary {
  checks?: {
    total?: number
    pass?: number
    warning?: number
    fail?: number
    unknown?: number
  }
}

interface ComplianceDetails {
  status?: string
  sections?: NtiaSection[]
  summary?: NtiaSummary
}

const props = withDefaults(defineProps<{
  status: string
  complianceDetails?: ComplianceDetails | string | null
  isPublicView?: boolean
}>(), {
  status: 'unknown',
  complianceDetails: null,
  isPublicView: false,
})

const activeIndex = ref(0)

const normalizedDetails = computed<ComplianceDetails>(() => {
  if (!props.complianceDetails) {
    return {}
  }

  if (typeof props.complianceDetails === 'string') {
    try {
      return JSON.parse(props.complianceDetails) as ComplianceDetails
    } catch {
      return {}
    }
  }

  return props.complianceDetails
})

const status = computed(() => normalizedDetails.value.status || props.status)

const wizardSteps = computed(() => {
  const sections = normalizedDetails.value.sections || []
  if (!sections.length) {
    return []
  }

  return sections.map((section, index) => ({
    id: section.name || `section-${index}`,
    name: section.name,
    title: section.title || `Section ${index + 1}`,
    summary: section.summary,
    status: section.status || 'unknown',
    checks: section.checks || [],
  }))
})

const currentStep = computed(() => wizardSteps.value[activeIndex.value] || null)

const checksSummary = computed(() => {
  const summary = normalizedDetails.value.summary?.checks
  if (!summary) {
    return {
      total: wizardSteps.value.reduce((total, step) => total + step.checks.length, 0),
      pass: 0,
      warning: 0,
      fail: 0,
      unknown: 0,
    }
  }

  return {
    total: summary.total ?? 0,
    pass: summary.pass ?? 0,
    warning: summary.warning ?? 0,
    fail: summary.fail ?? 0,
    unknown: summary.unknown ?? 0,
  }
})

const actionableChecks = computed(() =>
  wizardSteps.value
    .flatMap(step => step.checks)
    .filter(check => ['fail', 'warning'].includes((check.status || '').toLowerCase()))
)

const statusBadgeClass = computed(() => stepStatusBadgeClass(status.value))

const formatStatus = (value?: string | null) => {
  switch ((value || 'unknown').toLowerCase()) {
    case 'compliant':
      return 'Compliant'
    case 'partial':
    case 'warning':
      return 'Partially Compliant'
    case 'non_compliant':
    case 'fail':
      return 'Not Compliant'
    default:
      return 'Unknown'
  }
}

const stepperItemClass = (index: number, stepStatus?: string | null) => {
  const classes = []
  if (index === activeIndex.value) {
    classes.push('is-active')
  } else if (index < activeIndex.value) {
    classes.push('is-complete')
  }

  const normalized = (stepStatus || '').toLowerCase()
  if (normalized === 'fail') {
    classes.push('is-error')
  } else if (normalized === 'warning') {
    classes.push('is-warning')
  } else if (normalized === 'pass' || normalized === 'compliant') {
    classes.push('is-success')
  }
  return classes
}

const stepStatusBadgeClass = (stepStatus?: string | null) => {
  switch ((stepStatus || '').toLowerCase()) {
    case 'fail':
    case 'non_compliant':
      return 'bg-danger-subtle text-danger'
    case 'warning':
    case 'partial':
      return 'bg-warning-subtle text-warning'
    case 'pass':
    case 'compliant':
      return 'bg-success-subtle text-success'
    default:
      return 'bg-secondary-subtle text-secondary'
  }
}

const stepStatusIcon = (stepStatus?: string | null) => {
  switch ((stepStatus || '').toLowerCase()) {
    case 'fail':
    case 'non_compliant':
      return 'fas fa-times-circle text-danger'
    case 'warning':
    case 'partial':
      return 'fas fa-exclamation-circle text-warning'
    case 'pass':
    case 'compliant':
      return 'fas fa-check-circle text-success'
    default:
      return 'fas fa-circle text-secondary'
  }
}

const checkClass = (checkStatus?: string | null) => {
  switch ((checkStatus || '').toLowerCase()) {
    case 'fail':
      return 'ntia-check-item--error'
    case 'warning':
      return 'ntia-check-item--warning'
    case 'pass':
      return 'ntia-check-item--success'
    default:
      return 'ntia-check-item--info'
  }
}

const checkStatusIcon = (checkStatus?: string | null) => {
  switch ((checkStatus || '').toLowerCase()) {
    case 'fail':
      return 'fas fa-times-circle text-danger'
    case 'warning':
      return 'fas fa-exclamation-circle text-warning'
    case 'pass':
      return 'fas fa-check-circle text-success'
    default:
      return 'fas fa-info-circle text-secondary'
  }
}

const goToPreviousStep = () => {
  if (activeIndex.value > 0) {
    activeIndex.value -= 1
  }
}

const goToNextStep = () => {
  if (activeIndex.value < wizardSteps.value.length - 1) {
    activeIndex.value += 1
  }
}
</script>

<style scoped>
.ntia-assistant-card {
  background: #ffffff;
  border-radius: 1rem;
  border: 1px solid #e2e8f0;
  padding: 1.75rem;
  box-shadow: 0 10px 30px rgba(15, 23, 42, 0.08);
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

.ntia-assistant-card__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
}

.ntia-assistant-card__title {
  display: flex;
  align-items: flex-start;
  gap: 0.85rem;
}

.ntia-assistant-card__title h2 {
  font-size: 1.25rem;
  font-weight: 700;
  margin: 0;
}

.ntia-assistant-card__summary {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 0.75rem;
}

.summary-tile {
  background: #f8fafc;
  border-radius: 0.75rem;
  padding: 1rem;
  text-align: center;
  border: 1px solid #e2e8f0;
}

.summary-label {
  display: block;
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: #64748b;
  margin-bottom: 0.35rem;
}

.summary-value {
  font-size: 1.5rem;
  font-weight: 700;
  color: #0f172a;
}

.summary-tile--success {
  background: rgba(34, 197, 94, 0.1);
  border-color: rgba(34, 197, 94, 0.4);
  color: #15803d;
}

.summary-tile--warning {
  background: rgba(245, 158, 11, 0.1);
  border-color: rgba(245, 158, 11, 0.4);
  color: #b45309;
}

.summary-tile--error {
  background: rgba(239, 68, 68, 0.1);
  border-color: rgba(239, 68, 68, 0.4);
  color: #b91c1c;
}

.ntia-assistant-card__empty {
  text-align: center;
  padding: 1.5rem;
  border: 1px dashed #cbd5f5;
  border-radius: 1rem;
  background: rgba(99, 102, 241, 0.04);
}

.ntia-assistant-card__empty i {
  font-size: 1.75rem;
  color: #6366f1;
}

.ntia-stepper {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
}

.ntia-stepper__item {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 0.75rem;
  padding: 0.75rem 1rem;
  display: flex;
  align-items: center;
  gap: 0.75rem;
  cursor: pointer;
  transition: all 0.2s ease-in-out;
  flex: 1 1 220px;
  min-width: 200px;
}

.ntia-stepper__item.is-active {
  border-color: rgba(79, 70, 229, 0.9);
  box-shadow: 0 6px 20px rgba(79, 70, 229, 0.12);
  background: linear-gradient(135deg, rgba(79, 70, 229, 0.1), rgba(79, 70, 229, 0.05));
}

.ntia-stepper__item.is-complete {
  border-color: rgba(34, 197, 94, 0.4);
  background: rgba(34, 197, 94, 0.08);
}

.ntia-stepper__indicator {
  width: 32px;
  height: 32px;
  border-radius: 999px;
  background: #ffffff;
  display: grid;
  place-items: center;
  box-shadow: 0 2px 4px rgba(15, 23, 42, 0.12);
}

.ntia-stepper__title {
  font-weight: 600;
  color: #0f172a;
  text-align: left;
}

.ntia-step-card {
  border: 1px solid #e2e8f0;
  border-radius: 1rem;
  padding: 1.5rem;
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
  background: #ffffff;
}

.ntia-step-card__header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 1rem;
}

.ntia-step-card__title {
  font-size: 1.1rem;
  font-weight: 700;
  margin-bottom: 0.35rem;
}

.ntia-step-card__content {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.ntia-check-item {
  border-radius: 0.75rem;
  border: 1px solid #e2e8f0;
  padding: 1rem;
  background: #f8fafc;
  display: flex;
  gap: 1rem;
  transition: transform 0.2s ease;
}

.ntia-check-item:hover {
  transform: translateY(-1px);
  box-shadow: 0 8px 16px rgba(15, 23, 42, 0.08);
}

.ntia-check-item__meta {
  display: flex;
  gap: 1rem;
}

.ntia-check-item__icon {
  font-size: 1.35rem;
  display: grid;
  place-items: center;
  width: 36px;
}

.ntia-check-item__title {
  font-weight: 600;
  margin-bottom: 0.35rem;
}

.ntia-check-item__message {
  margin-bottom: 0;
  color: #475569;
}

.ntia-check-item__suggestion {
  font-size: 0.9rem;
  margin-bottom: 0.25rem;
  color: #2563eb;
  display: flex;
  align-items: center;
  gap: 0.3rem;
}

.ntia-check-item__affected {
  font-size: 0.85rem;
  color: #475569;
}

.ntia-check-item--error {
  border-color: rgba(239, 68, 68, 0.4);
  background: rgba(254, 202, 202, 0.2);
}

.ntia-check-item--warning {
  border-color: rgba(245, 158, 11, 0.4);
  background: rgba(254, 240, 138, 0.2);
}

.ntia-check-item--success {
  border-color: rgba(34, 197, 94, 0.3);
  background: rgba(220, 252, 231, 0.2);
}

.ntia-step-card__footer {
  display: flex;
  align-items: center;
  gap: 1rem;
}

.ntia-assistant-card__actions {
  border-top: 1px solid #e2e8f0;
  padding-top: 1.5rem;
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

.ntia-action-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.ntia-action-list__item {
  display: flex;
  gap: 1rem;
  border: 1px solid #e2e8f0;
  border-radius: 0.75rem;
  padding: 1rem;
  background: #f8fafc;
}

.ntia-action-list__icon {
  width: 36px;
  display: grid;
  place-items: center;
  font-size: 1.25rem;
}

.ntia-action-list__body h4 {
  font-size: 1rem;
  font-weight: 600;
  margin-bottom: 0.25rem;
}

.ntia-resource-links {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  gap: 1rem;
  flex-wrap: wrap;
}

.ntia-resource-links a {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  color: #2563eb;
  font-weight: 600;
  text-decoration: none;
}

.ntia-resource-links a:hover {
  text-decoration: underline;
}

@media (max-width: 992px) {
  .ntia-assistant-card {
    padding: 1.25rem;
  }

  .ntia-stepper__item {
    flex: 1 1 100%;
  }
}
</style>
