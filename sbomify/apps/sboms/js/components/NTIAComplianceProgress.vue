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

    <section v-if="hasData" class="ntia-progress-card__body">
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
            {{ segment.count }} SBOM{{ segment.count === 1 ? '' : 's' }}
          </span>
        </li>
      </ul>

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
    </section>

    <section v-else class="ntia-progress-card__empty">
      <i class="fas fa-clipboard-list mb-3 text-secondary"></i>
      <p class="mb-2">No NTIA compliance data available yet.</p>
      <p class="text-muted mb-0">
        Run the NTIA compliance check to see progress across this {{ summary.scope || 'scope' }}.
      </p>
    </section>

    <footer class="ntia-progress-card__footer">
      <small class="text-muted">
        Last checked:
        <span class="fw-semibold">{{ lastCheckedDisplay }}</span>
      </small>
    </footer>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

type NtiaStatus = 'compliant' | 'partial' | 'non_compliant' | 'unknown'

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
}

interface Props {
  summary?: Summary | string | null
  summaryElementId?: string
  scope?: string
  scopeName?: string
}

const props = defineProps<Props>()

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
    summaryData.value = props.summary
    return
  }

  if (typeof props.summary === 'string') {
    summaryData.value = parseSummaryString(props.summary)
    return
  }

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

const hasData = computed(() => (summary.value.total ?? 0) > 0)

const scoreDisplay = computed(() => {
  if (!hasData.value) {
    return '--'
  }
  const score = summary.value.score ?? 0
  return `${score.toFixed(1)}%`
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
</script>

<style scoped>
.ntia-progress-card {
  background: #ffffff;
  border-radius: 1rem;
  border: 1px solid #e2e8f0;
  padding: 1.5rem;
  box-shadow: 0 8px 24px rgba(15, 23, 42, 0.07);
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
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
  margin-bottom: 0.35rem;
}

.ntia-progress-card__subtitle {
  font-size: 0.85rem;
}

.ntia-score {
  display: flex;
  align-items: baseline;
  gap: 0.75rem;
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
  gap: 1rem 1.5rem;
  margin: 0;
  padding: 0;
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

.ntia-progress-meta__value {
  font-size: 1.1rem;
  font-weight: 700;
  color: #0f172a;
}

.ntia-progress-card__empty {
  text-align: center;
  padding: 1.5rem;
  border: 1px dashed #cbd5f5;
  border-radius: 1rem;
  background: rgba(99, 102, 241, 0.04);
}

.ntia-progress-card__footer {
  border-top: 1px solid #e2e8f0;
  padding-top: 1rem;
  text-align: right;
}

@media (max-width: 768px) {
  .ntia-progress-card {
    padding: 1.25rem;
  }

  .ntia-progress-legend {
    flex-direction: column;
    align-items: flex-start;
  }

  .ntia-progress-meta {
    grid-template-columns: 1fr;
  }
}
</style>
