<template>
  <StandardCard
    title="Artifacts in this Release"
    :info-icon="'fas fa-puzzle-piece'"
    variant="default"
    shadow="sm"
  >
    <!-- Loading State -->
    <div v-if="isLoading" class="text-center py-4">
      <div class="spinner-border text-primary" role="status">
        <span class="visually-hidden">Loading...</span>
      </div>
      <p class="mb-0 mt-2">Loading artifacts...</p>
    </div>

    <!-- Error State -->
    <div v-else-if="error" class="alert alert-danger">
      <p class="mb-0">Failed to load artifacts.</p>
    </div>

    <!-- Empty State -->
    <div v-else-if="!hasData" class="text-center py-4 text-muted">
      <div class="empty-icon mb-3">
        <i class="fas fa-puzzle-piece fa-3x opacity-25"></i>
      </div>
      <h5>No artifacts in this release</h5>
      <p class="mb-0">This release doesn't contain any artifacts yet.</p>
    </div>

    <!-- Artifacts Content -->
    <div v-else>
      <!-- Search and Filter Controls -->
      <div v-if="artifacts.length > 10" class="artifacts-controls mb-3">
        <div class="row align-items-center">
          <div class="col-md-6">
            <div class="input-group">
              <span class="input-group-text">
                <i class="fas fa-search"></i>
              </span>
              <input
                v-model="searchQuery"
                type="text"
                class="form-control"
                placeholder="Search artifacts..."
              >
            </div>
          </div>
          <div class="col-md-3">
            <select v-model="filterType" class="form-select">
              <option value="">All Types</option>
              <option value="sbom">SBOMs</option>
              <option value="document">Documents</option>
            </select>
          </div>
          <div class="col-md-3">
            <select v-model="itemsPerPage" class="form-select">
              <option :value="10">10 per page</option>
              <option :value="25">25 per page</option>
              <option :value="50">50 per page</option>
              <option :value="100">100 per page</option>
            </select>
          </div>
        </div>
      </div>

      <!-- Results Summary -->
      <div v-if="artifacts.length > itemsPerPage" class="d-flex justify-content-between align-items-center mb-3">
        <small class="text-muted">
          Showing {{ paginatedArtifacts.length }} of {{ filteredArtifacts.length }} artifacts
          <span v-if="filteredArtifacts.length !== artifacts.length">
            (filtered from {{ artifacts.length }} total)
          </span>
        </small>
      </div>

      <!-- Artifacts Table -->
      <div class="table-responsive">
        <table class="table artifacts-table">
          <thead>
            <tr>
              <th>Type</th>
              <th>Name</th>
              <th>Component</th>
              <th>Format</th>
              <th>Version</th>
              <th>Created</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="artifact in paginatedArtifacts" :key="artifact.id">
              <td>
                <span class="artifact-type-icon" :class="getArtifactIconClass(artifact)">
                  <i :class="getArtifactIcon(artifact)"></i>
                </span>
              </td>
              <td>
                <div class="artifact-name">
                  <div class="fw-medium">{{ getArtifactName(artifact) }}</div>
                  <div v-if="getArtifactType(artifact)" class="artifact-type-badge">
                    {{ getArtifactType(artifact) }}
                  </div>
                </div>
              </td>
              <td>
                <span class="component-name">{{ getComponentName(artifact) }}</span>
              </td>
              <td>
                <span class="format-text">{{ getArtifactFormat(artifact) }}</span>
              </td>
              <td>
                <span v-if="getArtifactVersion(artifact)" :title="getArtifactVersion(artifact)">
                  {{ truncateText(getArtifactVersion(artifact), 20) }}
                </span>
                <span v-else class="text-muted">—</span>
              </td>
              <td>
                <small class="text-muted">{{ formatDate(getArtifactCreatedAt(artifact)) }}</small>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Pagination Controls -->
      <PaginationControls
        v-if="totalPages > 1"
        v-model:current-page="currentPage"
        v-model:page-size="itemsPerPage"
        :total-pages="totalPages"
        :total-items="filteredArtifacts.length"
        :show-page-size-selector="true"
      />
    </div>
  </StandardCard>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import StandardCard from './StandardCard.vue'
import PaginationControls from './PaginationControls.vue'

interface Component {
  id: string
  name: string
}

interface SBOM {
  id: string
  name: string
  format: string
  format_version: string
  version: string
  created_at: string
  component: Component
}

interface Document {
  id: string
  name: string
  document_type: string
  version: string
  created_at: string
  component: Component
}

interface Artifact {
  id: string
  sbom?: SBOM | null
  document?: Document | null
  created_at: string
}

interface Props {
  releaseId: string
  productId: string
  artifactsDataElementId?: string
}

const props = withDefaults(defineProps<Props>(), {
  artifactsDataElementId: 'artifacts-data'
})

// State
const artifacts = ref<Artifact[]>([])
const isLoading = ref(false)
const error = ref<string | null>(null)
const searchQuery = ref('')
const filterType = ref('')
const currentPage = ref(1)
const itemsPerPage = ref(25)

// Computed
const hasData = computed(() => artifacts.value.length > 0)

const filteredArtifacts = computed(() => {
  let filtered = artifacts.value

  // Apply search filter
  if (searchQuery.value.trim()) {
    const query = searchQuery.value.toLowerCase().trim()
    filtered = filtered.filter(artifact =>
      getArtifactName(artifact).toLowerCase().includes(query) ||
      getComponentName(artifact).toLowerCase().includes(query) ||
      getArtifactFormat(artifact).toLowerCase().includes(query) ||
      (getArtifactVersion(artifact) && getArtifactVersion(artifact).toLowerCase().includes(query))
    )
  }

  // Apply type filter
  if (filterType.value) {
    filtered = filtered.filter(artifact => {
      if (filterType.value === 'sbom') {
        return artifact.sbom
      } else if (filterType.value === 'document') {
        return artifact.document
      }
      return true
    })
  }

  return filtered
})

const totalPages = computed(() => {
  return Math.ceil(filteredArtifacts.value.length / itemsPerPage.value)
})

const paginatedArtifacts = computed(() => {
  const start = (currentPage.value - 1) * itemsPerPage.value
  const end = start + itemsPerPage.value
  return filteredArtifacts.value.slice(start, end)
})

// Methods
const getArtifactName = (artifact: Artifact): string => {
  if (artifact.sbom) return artifact.sbom.name
  if (artifact.document) return artifact.document.name
  return 'Unknown'
}

const getComponentName = (artifact: Artifact): string => {
  if (artifact.sbom) return artifact.sbom.component.name
  if (artifact.document) return artifact.document.component.name
  return 'Unknown'
}

const getArtifactFormat = (artifact: Artifact): string => {
  if (artifact.sbom) {
    const format = artifact.sbom.format.toLowerCase() === 'cyclonedx' ? 'CycloneDX' :
                   artifact.sbom.format.toLowerCase() === 'spdx' ? 'SPDX' :
                   artifact.sbom.format.charAt(0).toUpperCase() + artifact.sbom.format.slice(1).toLowerCase()
    return `${format} ${artifact.sbom.format_version}`
  }
  if (artifact.document) {
    return artifact.document.document_type.charAt(0).toUpperCase() +
           artifact.document.document_type.slice(1).toLowerCase()
  }
  return 'Unknown'
}

const getArtifactVersion = (artifact: Artifact): string => {
  if (artifact.sbom) return artifact.sbom.version
  if (artifact.document) return artifact.document.version
  return ''
}

const getArtifactCreatedAt = (artifact: Artifact): string => {
  if (artifact.sbom) return artifact.sbom.created_at
  if (artifact.document) return artifact.document.created_at
  return artifact.created_at
}

const getArtifactType = (artifact: Artifact): string => {
  if (artifact.sbom) {
    const format = artifact.sbom.format.toLowerCase() === 'cyclonedx' ? 'CycloneDX' :
                   artifact.sbom.format.toLowerCase() === 'spdx' ? 'SPDX' :
                   artifact.sbom.format.charAt(0).toUpperCase() + artifact.sbom.format.slice(1).toLowerCase()
    return `SBOM • ${format}`
  }
  if (artifact.document) {
    return `Document • ${artifact.document.document_type.charAt(0).toUpperCase() + artifact.document.document_type.slice(1).toLowerCase()}`
  }
  return 'Unknown'
}

const getArtifactIcon = (artifact: Artifact): string => {
  if (artifact.sbom) return 'fas fa-file-code'
  if (artifact.document) return 'fas fa-file-alt'
  return 'fas fa-file'
}

const getArtifactIconClass = (artifact: Artifact): string => {
  if (artifact.sbom) return 'sbom-icon'
  if (artifact.document) return 'document-icon'
  return 'unknown-icon'
}

const formatDate = (dateString: string): string => {
  return new Date(dateString).toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric'
  })
}

const truncateText = (text: string, maxLength: number): string => {
  if (!text || text.length <= maxLength) return text
  return text.substring(0, maxLength - 3) + '...'
}

const loadArtifacts = () => {
  try {
    const element = document.getElementById(props.artifactsDataElementId)
    if (element && element.textContent) {
      const parsed = JSON.parse(element.textContent)
      if (Array.isArray(parsed)) {
        artifacts.value = parsed
        return
      }
    }

    // If no data found, set empty array
    artifacts.value = []
  } catch (err) {
    console.error('Error parsing artifacts data:', err)
    error.value = 'Failed to parse artifacts data'
    artifacts.value = []
  }
}

// Lifecycle
onMounted(() => {
  loadArtifacts()
})
</script>

<style scoped>
.artifacts-controls {
  background: #f8f9fa;
  padding: 1rem;
  border-radius: 0.5rem;
  border: 1px solid #e9ecef;
}

.artifacts-table {
  margin-bottom: 0;
}

.artifacts-table th {
  border-top: none;
  font-weight: 600;
  color: #495057;
  background-color: #f8f9fa;
  font-size: 0.875rem;
}

.artifacts-table td {
  vertical-align: middle;
  padding: 0.75rem;
}

.artifact-type-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: 8px;
  font-size: 0.875rem;
}

.sbom-icon {
  background: linear-gradient(135deg, #10b981, #059669);
  color: white;
}

.document-icon {
  background: linear-gradient(135deg, #f59e0b, #d97706);
  color: white;
}

.unknown-icon {
  background: #e5e7eb;
  color: #6b7280;
}

.artifact-name {
  min-width: 200px;
}

.artifact-type-badge {
  font-size: 0.75rem;
  color: #6366f1;
  font-weight: 500;
}

.component-name {
  color: #64748b;
  font-weight: 500;
}

.format-text {
  font-family: 'Monaco', 'Consolas', monospace;
  font-size: 0.875rem;
  background: #f1f5f9;
  padding: 0.25rem 0.5rem;
  border-radius: 0.25rem;
  color: #475569;
}

.empty-icon {
  font-size: 3rem;
}

@media (max-width: 768px) {
  .artifacts-controls .row > div {
    margin-bottom: 0.5rem;
  }

  .table-responsive {
    font-size: 0.875rem;
  }

  .artifact-name {
    min-width: 150px;
  }
}
</style>