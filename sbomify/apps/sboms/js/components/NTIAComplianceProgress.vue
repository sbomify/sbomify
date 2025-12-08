<template>
  <div class="ntia-progress-card">
    <header class="ntia-progress-card__header">
      <div>
        <h3 class="ntia-progress-card__title">
          <i class="fas fa-chart-line me-2 text-primary"></i>
          NTIA Compliance Progress
        </h3>
        <p class="ntia-progress-card__subtitle text-muted mb-0" v-if="scopeLabel">
          {{ scopeLabel }}
        </p>
      </div>
      <span class="badge" :class="statusBadgeClass">
        {{ statusLabel }}
      </span>
    </header>

    <section v-if="isLoading" class="ntia-progress-card__body">
      <div class="ntia-score">
        <div class="ntia-score__value skeleton" style="width: 90px; height: 38px;"></div>
        <div class="ntia-score__label text-muted">Compliance Score</div>
      </div>
      <div class="ntia-progress-bar skeleton" role="progressbar" aria-label="NTIA compliance distribution"></div>
      <ul class="ntia-progress-legend">
        <li v-for="segment in progressSegments" :key="`${segment.status}-legend-skeleton`">
          <span class="ntia-progress-legend__dot" :class="`ntia-progress-legend__dot--${segment.status}`"></span>
          <span class="skeleton" style="width: 80px; height: 12px;"></span>
          <span class="skeleton" style="width: 50px; height: 12px;"></span>
        </li>
      </ul>
      <div class="ntia-progress-meta">
        <div class="ntia-progress-meta__item" v-for="n in 3" :key="`meta-skeleton-${n}`">
          <span class="ntia-progress-meta__label skeleton" style="width: 70%; height: 12px;"></span>
          <span class="ntia-progress-meta__value skeleton" style="width: 40%; height: 16px;"></span>
        </div>
      </div>
    </section>

    <section v-else-if="hasData" class="ntia-progress-card__body">
      <div class="ntia-score">
        <div class="ntia-score__value">{{ scoreDisplay }}</div>
        <div class="ntia-score__label text-muted">Compliance Score</div>
      </div>

      <div class="ntia-progress-bar" role="progressbar" aria-label="NTIA compliance distribution">
        <div
          v-for="segment in progressSegments"
          :key="segment.status"
          class="ntia-progress-bar__segment"
          :class="`ntia-progress-bar__segment--${segment.status}`"
          :style="{ width: `${segment.percentage}%` }"
        >
          <span class="visually-hidden">
            {{ segment.label }}: {{ segment.percentage }}%
          </span>
        </div>
      </div>

      <ul class="ntia-progress-legend">
        <li v-for="segment in progressSegments" :key="`${segment.status}-legend`">
          <span class="ntia-progress-legend__dot" :class="`ntia-progress-legend__dot--${segment.status}`"></span>
          <span class="ntia-progress-legend__label">{{ segment.label }}</span>
          <span class="ntia-progress-legend__count">
            {{ segment.count }} SBOM{{ segment.count === 1 ? '' : 's' }} · {{ segment.percentage }}%
          </span>
        </li>
      </ul>

      <div v-if="highlightedSegment" class="ntia-progress-callout">
        <i class="fas fa-exclamation-triangle"></i>
        <div>
          <p class="ntia-progress-callout__title mb-1">Action needed</p>
          <small>
            {{ highlightedSegment.count }} SBOM{{ highlightedSegment.count === 1 ? '' : 's' }} are
            {{ STATUS_CONFIG[highlightedSegment.status as NtiaStatus].label.toLowerCase() }}.
            Focus here to improve your score.
          </small>
        </div>
      </div>

      <div class="ntia-progress-meta">
        <div class="ntia-progress-meta__item">
          <span class="ntia-progress-meta__label text-muted">Total SBOMs</span>
          <span class="ntia-progress-meta__value">{{ summary.total }}</span>
        </div>
        <div class="ntia-progress-meta__item">
          <span class="ntia-progress-meta__label text-muted">Warnings</span>
          <span class="ntia-progress-meta__value text-warning fw-semibold">{{ summary.warnings ?? 0 }}</span>
        </div>
        <div class="ntia-progress-meta__item">
          <span class="ntia-progress-meta__label text-muted">Errors</span>
          <span class="ntia-progress-meta__value text-danger fw-semibold">{{ summary.errors ?? 0 }}</span>
        </div>
      </div>

      <div v-if="hasVulnerabilities" class="ntia-vulnerabilities">
        <div class="ntia-vulnerabilities__header">
          <i class="fas fa-shield-alt me-2"></i>
          <span class="fw-semibold">Vulnerabilities</span>
          <span class="ntia-vulnerabilities__total">{{ totalVulnerabilities }}</span>
        </div>
        <div class="ntia-vulnerabilities__grid">
          <div class="ntia-vulnerabilities__item ntia-vulnerabilities__item--critical">
            <span class="ntia-vulnerabilities__count">{{ vulnerabilityCounts.critical }}</span>
            <span class="ntia-vulnerabilities__label">Critical</span>
          </div>
          <div class="ntia-vulnerabilities__item ntia-vulnerabilities__item--high">
            <span class="ntia-vulnerabilities__count">{{ vulnerabilityCounts.high }}</span>
            <span class="ntia-vulnerabilities__label">High</span>
          </div>
          <div class="ntia-vulnerabilities__item ntia-vulnerabilities__item--medium">
            <span class="ntia-vulnerabilities__count">{{ vulnerabilityCounts.medium }}</span>
            <span class="ntia-vulnerabilities__label">Medium</span>
          </div>
          <div class="ntia-vulnerabilities__item ntia-vulnerabilities__item--low">
            <span class="ntia-vulnerabilities__count">{{ vulnerabilityCounts.low }}</span>
            <span class="ntia-vulnerabilities__label">Low</span>
          </div>
        </div>
      </div>
    </section>

    <section v-else class="ntia-progress-card__empty">
      <i class="fas fa-clipboard-list mb-3 text-secondary"></i>
      <p class="mb-2">No NTIA compliance data available yet.</p>
      <p class="text-muted mb-0">
        Run the NTIA compliance check to see progress across this {{ summary.scope || 'scope' }}.
      </p>
    </section>

    <footer class="ntia-progress-card__footer">
      <div class="d-flex flex-wrap align-items-center justify-content-between gap-2">
        <small class="text-muted">
          Last checked:
          <span class="fw-semibold">{{ lastCheckedDisplay }}</span>
        </small>
        <div v-if="enableActions" class="ntia-actions">
          <span class="text-muted small">Keep your NTIA posture current.</span>
          <button class="btn btn-primary btn-sm" type="button" :disabled="isLoading" @click="emit('refresh')">
            <i class="fas fa-rotate me-2"></i>
            {{ primaryActionLabel }}
          </button>
        </div>
      </div>
    </footer>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

type NtiaStatus = 'compliant' | 'partial' | 'non_compliant' | 'unknown'

interface VulnerabilityCounts {
  critical?: number
  high?: number
  medium?: number
  low?: number
  unknown?: number
}

interface Summary {
  scope?: string | null
  scope_id?: string | null
  scope_name?: string | null
  total?: number
  status?: string | null
  score?: number | null
  counts?: Record<string, number>
  percentages?: Record<string, number>
  warnings?: number | null
  errors?: number | null
  last_checked_at?: string | null
  vulnerabilities?: VulnerabilityCounts | null
}

interface Props {
  summary?: Summary | string | null
  summaryElementId?: string
  scope?: string
  scopeName?: string
  loading?: boolean
  enableActions?: boolean
}

const props = defineProps<Props>()
const emit = defineEmits<{ (e: 'refresh'): void }>()

const summaryData = ref<Summary | null>(null)

const STATUS_CONFIG: Record<NtiaStatus, { label: string }> = {
  compliant: { label: 'Compliant' },
  partial: { label: 'Partially Compliant' },
  non_compliant: { label: 'Not Compliant' },
  unknown: { label: 'Unknown' },
}

const STATUS_ORDER: NtiaStatus[] = ['compliant', 'partial', 'non_compliant', 'unknown']

const parseSummaryString = (value: string | null | undefined): Summary | null => {
  if (!value) {
    return null
  }
  try {
    return JSON.parse(value) as Summary
  } catch {
    return null
  }
}

const loadSummary = () => {
  if (props.summary && typeof props.summary !== 'string') {
    summaryData.value = { ...props.summary }
    return
  }

  if (typeof props.summary === 'string') {
    summaryData.value = parseSummaryString(props.summary)
    return
  }

  summaryData.value = null

  if (props.summaryElementId) {
    const scriptEl = document.getElementById(props.summaryElementId)
    if (scriptEl?.textContent) {
      summaryData.value = parseSummaryString(scriptEl.textContent)
    }
  }
}

onMounted(() => {
  loadSummary()
})

watch(
  () => props.summary,
  () => {
    loadSummary()
  }
)

const summary = computed<Summary>(() => {
  const base: Summary = summaryData.value ? { ...summaryData.value } : {}

  if (props.scope && !base.scope) {
    base.scope = props.scope
  }
  if (props.scopeName && !base.scope_name) {
    base.scope_name = props.scopeName
  }

  if (!base.counts) {
    base.counts = {}
  }
  if (!base.percentages) {
    base.percentages = {}
  }

  return base
})

const isLoading = computed(() => props.loading === true)
const hasData = computed(() => (summary.value.total ?? 0) > 0)

const resolvedCounts = computed(() => {
  const counts: Record<NtiaStatus, number> = {
    compliant: 0,
    partial: 0,
    non_compliant: 0,
    unknown: 0,
  }

  STATUS_ORDER.forEach(status => {
    const value = summary.value.counts?.[status]
    counts[status] = typeof value === 'number' ? value : 0
  })

  return counts
})

const complianceScore = computed(() => {
  // First, try to calculate from counts (most accurate)
  const total = summary.value.total ?? 0
  if (total > 0) {
    const counts = resolvedCounts.value
    const computedScore = ((counts.compliant + 0.5 * counts.partial) / total) * 100
    return Math.min(100, Math.max(0, Number(computedScore.toFixed(1))))
  }

  // Fallback to backend score if available and valid
  const raw = summary.value.score
  if (raw !== undefined && raw !== null) {
    const parsed = Number(raw)
    if (!Number.isNaN(parsed) && parsed > 0) {
      return Math.min(100, Math.max(0, parsed))
    }
  }

  return null
})

const scoreDisplay = computed(() => {
  if (!hasData.value || complianceScore.value === null) {
    return '--'
  }
  return `${complianceScore.value.toFixed(1)}%`
})

const scopeLabel = computed(() => {
  const scope = summary.value.scope
  if (!scope) {
    return null
  }

  const scopeName = summary.value.scope_name
  if (scopeName) {
    return `${scopeName} · ${scope.replace('_', ' ').toUpperCase()}`
  }

  return scope.replace('_', ' ').toUpperCase()
})

const progressSegments = computed(() =>
  STATUS_ORDER.map(status => {
    const count = resolvedCounts.value[status]
    const total = summary.value.total ?? 0
    const percentage =
      total > 0
        ? Math.max(0, Math.min(100, summary.value.percentages?.[status] ?? (count / total) * 100))
        : 0
    return {
      status,
      label: STATUS_CONFIG[status].label,
      count,
      percentage: parseFloat(percentage.toFixed(1)),
    }
  }).filter(segment => segment.count > 0 || hasData.value === false)
)

const statusLabel = computed(() => STATUS_CONFIG[(summary.value.status || 'unknown') as NtiaStatus]?.label || 'Unknown')

const statusBadgeClass = computed(() => {
  switch ((summary.value.status || '').toLowerCase()) {
    case 'compliant':
      return 'bg-success-subtle text-success'
    case 'partial':
      return 'bg-warning-subtle text-warning'
    case 'non_compliant':
      return 'bg-danger-subtle text-danger'
    default:
      return 'bg-secondary-subtle text-secondary'
  }
})

const lastCheckedDisplay = computed(() => {
  if (isLoading.value) {
    return 'Refreshing...'
  }
  const value = summary.value.last_checked_at
  if (!value) {
    return 'Not yet assessed'
  }
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return value
  }
  return date.toLocaleString()
})

const highlightedSegment = computed(() => {
  // Prefer non-compliant > partial > unknown when there is data
  const ordered: NtiaStatus[] = ['non_compliant', 'partial', 'unknown']
  const segment = ordered
    .map(status => ({
      status,
      count: resolvedCounts.value[status],
      percentage: progressSegments.value.find(s => s.status === status)?.percentage ?? 0,
    }))
    .find(item => item.count > 0)

  if (segment) {
    return segment
  }

  return null
})

const primaryActionLabel = computed(() =>
  summary.value.total ? 'Re-run compliance checks' : 'Run compliance checks'
)

const vulnerabilityCounts = computed(() => {
  const vulns = summary.value.vulnerabilities
  return {
    critical: vulns?.critical ?? 0,
    high: vulns?.high ?? 0,
    medium: vulns?.medium ?? 0,
    low: vulns?.low ?? 0,
    unknown: vulns?.unknown ?? 0,
  }
})

const totalVulnerabilities = computed(() => {
  const counts = vulnerabilityCounts.value
  return counts.critical + counts.high + counts.medium + counts.low + counts.unknown
})

const hasVulnerabilities = computed(() => totalVulnerabilities.value > 0)
</script>

<style scoped>
.ntia-progress-card {
  background: #ffffff;
  border-radius: 1rem;
  border: 1px solid #e2e8f0;
  padding: 1.5rem 1.75rem;
  box-shadow: 0 8px 24px rgba(15, 23, 42, 0.07);
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

.ntia-progress-card__header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 1rem;
}

.ntia-progress-card__title {
  font-size: 1.1rem;
  font-weight: 700;
  margin-bottom: 0.4rem;
}

.ntia-progress-card__subtitle {
  font-size: 0.85rem;
}

.ntia-progress-card__body {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

.ntia-score {
  display: flex;
  align-items: baseline;
  gap: 0.85rem;
  padding-bottom: 0.25rem;
}

.ntia-score__value {
  font-size: 2.5rem;
  font-weight: 700;
  line-height: 1;
  color: #0f172a;
}

.ntia-score__label {
  font-size: 0.875rem;
}

.ntia-progress-bar {
  height: 14px;
  width: 100%;
  border-radius: 999px;
  background: #e2e8f0;
  overflow: hidden;
  display: flex;
}

.ntia-progress-bar__segment {
  height: 100%;
  transition: width 0.3s ease;
}

.ntia-progress-bar__segment--compliant {
  background: linear-gradient(135deg, rgba(34, 197, 94, 0.85), rgba(34, 197, 94, 0.65));
}

.ntia-progress-bar__segment--partial {
  background: linear-gradient(135deg, rgba(245, 158, 11, 0.85), rgba(245, 158, 11, 0.65));
}

.ntia-progress-bar__segment--non_compliant {
  background: linear-gradient(135deg, rgba(239, 68, 68, 0.9), rgba(239, 68, 68, 0.7));
}

.ntia-progress-bar__segment--unknown {
  background: linear-gradient(135deg, rgba(148, 163, 184, 0.8), rgba(148, 163, 184, 0.6));
}

.ntia-progress-legend {
  list-style: none;
  display: flex;
  flex-wrap: wrap;
  gap: 1rem 1.75rem;
  margin: 0;
  padding: 0.25rem 0;
}

.ntia-progress-legend li {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.9rem;
}

.ntia-progress-legend__dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  display: inline-block;
}

.ntia-progress-legend__dot--compliant {
  background: #22c55e;
}

.ntia-progress-legend__dot--partial {
  background: #f59e0b;
}

.ntia-progress-legend__dot--non_compliant {
  background: #ef4444;
}

.ntia-progress-legend__dot--unknown {
  background: #94a3b8;
}

.ntia-progress-legend__count {
  font-weight: 600;
  color: #0f172a;
}

.ntia-progress-meta {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 1rem;
  margin-top: 0.25rem;
}

.ntia-progress-meta__item {
  background: #f8fafc;
  border-radius: 0.75rem;
  padding: 0.85rem 1rem;
  border: 1px solid #e2e8f0;
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}

.ntia-progress-meta__label {
  font-size: 0.85rem;
}

.ntia-progress-meta__value {
  font-size: 1.1rem;
  font-weight: 700;
  color: #0f172a;
}

.ntia-progress-card__empty {
  text-align: center;
  padding: 1.75rem 1.5rem;
  border: 1px dashed #cbd5f5;
  border-radius: 1rem;
  background: rgba(99, 102, 241, 0.04);
}

.ntia-progress-card__footer {
  border-top: 1px solid #e2e8f0;
  padding-top: 1rem;
  text-align: right;
}

.ntia-progress-callout {
  background: linear-gradient(135deg, rgba(255, 243, 205, 0.8), rgba(255, 237, 213, 0.9));
  border: 1px solid #f6c453;
  color: #92400e;
  border-radius: 0.85rem;
  padding: 0.85rem 1rem;
  display: flex;
  align-items: center;
  gap: 0.85rem;
}

.ntia-progress-callout__title {
  font-weight: 700;
  margin: 0;
}

.ntia-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.85rem;
  flex-wrap: wrap;
  border-top: 1px dashed #e2e8f0;
  padding-top: 1rem;
}

.ntia-actions .btn {
  border-radius: 999px;
  padding: 0.5rem 1.125rem;
}

.skeleton {
  background: linear-gradient(90deg, #f1f5f9 25%, #e2e8f0 37%, #f1f5f9 63%);
  background-size: 400% 100%;
  animation: skeleton-loading 1.4s ease infinite;
  border-radius: 0.5rem;
}

@keyframes skeleton-loading {
  0% {
    background-position: 100% 50%;
  }
  100% {
    background-position: 0 50%;
  }
}

@media (max-width: 768px) {
  .ntia-progress-card {
    padding: 1.25rem;
    gap: 1.25rem;
  }

  .ntia-progress-legend {
    flex-direction: column;
    align-items: flex-start;
    gap: 0.85rem;
  }

  .ntia-progress-meta {
    grid-template-columns: 1fr;
    gap: 0.85rem;
  }

  .ntia-vulnerabilities__grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

.ntia-vulnerabilities {
  background: #f8fafc;
  border-radius: 0.75rem;
  border: 1px solid #e2e8f0;
  padding: 1rem;
  margin-top: 0.5rem;
}

.ntia-vulnerabilities__header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.85rem;
  font-size: 0.9rem;
  color: #64748b;
}

.ntia-vulnerabilities__total {
  background: #e2e8f0;
  color: #475569;
  padding: 0.125rem 0.5rem;
  border-radius: 999px;
  font-size: 0.75rem;
  font-weight: 600;
  margin-left: auto;
}

.ntia-vulnerabilities__grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 0.75rem;
}

.ntia-vulnerabilities__item {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 0.75rem 0.5rem;
  border-radius: 0.5rem;
  text-align: center;
}

.ntia-vulnerabilities__item--critical {
  background: rgba(220, 38, 38, 0.1);
  border: 1px solid rgba(220, 38, 38, 0.2);
}

.ntia-vulnerabilities__item--critical .ntia-vulnerabilities__count {
  color: #dc2626;
}

.ntia-vulnerabilities__item--high {
  background: rgba(234, 88, 12, 0.1);
  border: 1px solid rgba(234, 88, 12, 0.2);
}

.ntia-vulnerabilities__item--high .ntia-vulnerabilities__count {
  color: #ea580c;
}

.ntia-vulnerabilities__item--medium {
  background: rgba(202, 138, 4, 0.1);
  border: 1px solid rgba(202, 138, 4, 0.2);
}

.ntia-vulnerabilities__item--medium .ntia-vulnerabilities__count {
  color: #ca8a04;
}

.ntia-vulnerabilities__item--low {
  background: rgba(37, 99, 235, 0.1);
  border: 1px solid rgba(37, 99, 235, 0.2);
}

.ntia-vulnerabilities__item--low .ntia-vulnerabilities__count {
  color: #2563eb;
}

.ntia-vulnerabilities__count {
  font-size: 1.25rem;
  font-weight: 700;
  line-height: 1;
  margin-bottom: 0.25rem;
}

.ntia-vulnerabilities__label {
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 0.025em;
  color: #64748b;
  font-weight: 500;
}
</style>
