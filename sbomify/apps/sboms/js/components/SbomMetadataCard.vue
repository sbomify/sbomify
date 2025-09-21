<template>
  <StandardCard
    title="SBOM Metadata"
    info-icon="fas fa-info-circle"
    shadow="sm"
    :collapsible="true"
    :default-expanded="true"
    storage-key="sbom-metadata"
  >
        <div v-if="sbomData" class="metadata-content">
      <div class="metadata-item">
        <div class="metadata-label">
          <i class="fas fa-calendar-alt me-2 text-primary"></i>
          Uploaded On
        </div>
        <div class="metadata-value">{{ formatDate(sbomData.created_at) }}</div>
      </div>

      <div class="metadata-item">
        <div class="metadata-label">
          <i class="fas fa-source-branch me-2 text-primary"></i>
          Source
        </div>
        <div class="metadata-value">
          <span class="badge bg-info-subtle text-info">{{ sbomData.source_display }}</span>
        </div>
      </div>

      <div class="metadata-item">
        <div class="metadata-label">
          <i class="fas fa-file-code me-2 text-primary"></i>
          Format
        </div>
        <div class="metadata-value">
          <span class="badge bg-success-subtle text-success">
            {{ formatSbomFormat(sbomData.format) }} {{ sbomData.format_version }}
          </span>
        </div>
      </div>

      <div v-if="sbomData.version" class="metadata-item">
        <div class="metadata-label">
          <i class="fas fa-tag me-2 text-primary"></i>
          Version
        </div>
        <div class="metadata-value">
          <span class="version-display" :title="sbomData.version">{{ sbomData.version }}</span>
        </div>
      </div>

      <div class="metadata-item">
        <div class="metadata-label">
          <i class="fas fa-fingerprint me-2 text-primary"></i>
          SBOM ID
        </div>
        <div class="metadata-value">
          <span class="vc-copyable-value font-monospace" :data-value="sbomData.id">
            {{ sbomData.id }}
          </span>
        </div>
      </div>
    </div>
    <div v-else class="text-center text-muted py-4">
      <i class="fas fa-spinner fa-spin me-2"></i>
      Loading SBOM metadata...
    </div>
  </StandardCard>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import StandardCard from '../../../core/js/components/StandardCard.vue'

interface SbomData {
  id: string
  name: string
  created_at: string
  source_display: string
  format: string
  format_version: string
  version?: string
}

interface Props {
  sbomDataElementId?: string
  sbomId?: string
  sbomName?: string
  createdAt?: string
  sourceDisplay?: string
  format?: string
  formatVersion?: string | number
  version?: string
}

const props = defineProps<Props>()

const sbomData = ref<SbomData | null>(null)

const parseSbomData = (): void => {
  try {
    if (props.sbomDataElementId) {
      // Get data from JSON script element
      const element = document.getElementById(props.sbomDataElementId)
      if (element && element.textContent) {
        const parsed = JSON.parse(element.textContent)
        sbomData.value = parsed
        return
      }
    }

    // Fallback to individual props
    if (props.sbomId) {
      sbomData.value = {
        id: props.sbomId,
        name: props.sbomName || '',
        created_at: props.createdAt || '',
        source_display: props.sourceDisplay || '',
        format: props.format || '',
        format_version: String(props.formatVersion || ''),
        version: props.version
      }
    }
  } catch (err) {
    console.error('Error parsing SBOM data:', err)
  }
}

onMounted(() => {
  parseSbomData()
})

const formatDate = (dateString: string): string => {
  try {
    if (!dateString || dateString.trim() === '') {
      return 'Unknown'
    }

    const date = new Date(dateString)

    // Check if the date is invalid
    if (isNaN(date.getTime())) {
      console.warn('Invalid date string provided:', dateString)
      return 'Invalid Date'
    }

    return date.toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'long',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    })
  } catch (error) {
    console.error('Error formatting date:', error)
    return dateString
  }
}

const formatSbomFormat = (format: string): string => {
  switch (format.toLowerCase()) {
    case 'cyclonedx':
      return 'CycloneDX'
    case 'spdx':
      return 'SPDX'
    default:
      return format.toUpperCase()
  }
}
</script>

<style scoped>
.metadata-content {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.metadata-item {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.metadata-label {
  font-size: 0.875rem;
  font-weight: 600;
  color: #6b7280;
  display: flex;
  align-items: center;
}

.metadata-value {
  font-size: 0.9rem;
  color: #374151;
  display: flex;
  align-items: center;
}

.font-monospace {
  font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
  font-size: 0.8rem;
  background: #f1f5f9;
  padding: 0.25rem 0.5rem;
  border-radius: 4px;
  border: 1px solid #e2e8f0;
  cursor: pointer;
  transition: all 0.2s ease;
}

.font-monospace:hover {
  background: #e2e8f0;
  border-color: #cbd5e1;
}

.version-display {
  display: inline-block;
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: bottom;
}

@media (max-width: 768px) {
  .metadata-content {
    gap: 0.75rem;
  }

  .metadata-item {
    gap: 0.125rem;
  }
}
</style>