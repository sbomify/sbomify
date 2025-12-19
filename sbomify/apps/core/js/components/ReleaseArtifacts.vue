<template>
  <StandardCard
    title="Artifacts"
    variant="default"
    shadow="sm"
  >
    <template #header-actions>
      <button
        v-if="canModifyArtifacts"
        class="btn btn-primary px-4"
        @click="showAddArtifactModal"
      >
        <i class="fas fa-plus me-2"></i>Add Artifact
      </button>
      <div v-else-if="isLatestRelease && hasCrudPermissions" class="alert alert-info mb-0 py-2 px-3">
        <i class="fas fa-info-circle me-2"></i>
        <small>The "Latest" release is automatically managed and cannot be modified manually.</small>
      </div>
    </template>

    <!-- Loading State -->
    <div v-if="isLoading" class="dashboard-empty">
      <div class="spinner-border text-primary" role="status">
        <span class="visually-hidden">Loading...</span>
      </div>
      <p class="mb-0 mt-2">Loading artifacts...</p>
    </div>

    <!-- Error State -->
    <div v-else-if="error" class="alert alert-danger">
      <p class="mb-0">Failed to load artifacts. Please try refreshing the page.</p>
    </div>

    <!-- Empty State -->
    <div v-else-if="!hasData" class="dashboard-empty">
      <div class="empty-icon">
        <i class="fas fa-puzzle-piece"></i>
      </div>
      <h5>No artifacts yet</h5>
      <p class="mb-3 text-muted">Add artifacts to this release to get started</p>
      <button
        v-if="canModifyArtifacts"
        class="btn btn-primary"
        @click="showAddArtifactModal"
      >
        <i class="fas fa-plus me-2"></i>Add Artifact
      </button>
      <div v-else-if="isLatestRelease && hasCrudPermissions" class="text-muted">
        <small><i class="fas fa-info-circle me-1"></i>Latest release is automatically managed</small>
      </div>
    </div>

    <!-- Artifacts Table -->
    <div v-else class="artifacts-table-container">
      <!-- Search and Filter Controls -->
      <div class="table-controls mb-3">
        <div class="row g-2">
          <div class="col-md-6">
            <div class="input-group">
              <span class="input-group-text">
                <i class="fas fa-search"></i>
              </span>
              <input
                v-model="artifactsSearchQuery"
                type="text"
                class="form-control"
                placeholder="Search artifacts by name, component, or format..."
              >
            </div>
          </div>
          <div class="col-md-3">
            <select v-model="artifactsFilterType" class="form-select">
              <option value="">All Types</option>
              <option value="sbom">SBOMs Only</option>
              <option value="document">Documents Only</option>
            </select>
          </div>
          <div class="col-md-3">
            <select v-model="artifactsFilterComponent" class="form-select">
              <option value="">All Components</option>
              <option v-for="component in uniqueArtifactComponents" :key="component" :value="component">
                {{ component }}
              </option>
            </select>
          </div>
        </div>
      </div>

      <!-- Results Summary -->
      <div class="d-flex justify-content-between align-items-center mb-3">
        <small class="text-muted">
          Showing {{ paginatedFilteredArtifacts.length }} of {{ filteredDisplayArtifacts.length }} artifacts
          <span v-if="filteredDisplayArtifacts.length !== artifacts.length">
            (filtered from {{ artifacts.length }} total)
          </span>
        </small>
        <div class="d-flex align-items-center gap-2">
          <label class="small text-muted mb-0">Items per page:</label>
          <select v-model="artifactsPerPage" class="form-select form-select-sm" style="width: auto;">
            <option :value="10">10</option>
            <option :value="25">25</option>
            <option :value="50">50</option>
            <option :value="100">100</option>
          </select>
        </div>
      </div>

      <!-- Artifacts Table -->
      <div class="table-responsive">
        <table class="table table-hover">
          <thead class="table-light">
            <tr>
              <th style="width: 40px;">Type</th>
              <th>Name</th>
              <th>Component</th>
              <th>Format/Type</th>
              <th>Version</th>
              <th style="width: 120px;">Created</th>
              <th v-if="canModifyArtifacts" style="width: 80px;">Actions</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="artifact in paginatedFilteredArtifacts"
              :key="artifact.id"
              class="artifact-row"
            >
              <td>
                <div class="artifact-type-icon" :class="getArtifactIconClass(artifact)">
                  <i :class="getArtifactIcon(artifact)" class="fa-sm"></i>
                </div>
              </td>
              <td>
                <div class="artifact-name-cell">
                  <a
                    :href="getArtifactUrl(artifact)"
                    class="artifact-name-link fw-medium"
                  >
                    {{ getArtifactName(artifact) }}
                  </a>
                  <span class="artifact-type-badge ms-2" :class="getArtifactBadgeClass(artifact)">
                    {{ getArtifactType(artifact) }}
                  </span>
                </div>
              </td>
              <td>
                <a :href="getComponentUrl(artifact)" class="component-link">
                  {{ getComponentName(artifact) }}
                </a>
              </td>
              <td>
                <span class="format-text">{{ getArtifactFormat(artifact) }}</span>
              </td>
              <td>
                <span
                  v-if="getArtifactVersion(artifact)"
                  class="version-text version-display"
                  :title="getArtifactVersion(artifact) || ''"
                >
                  {{ truncateText(getArtifactVersion(artifact) || '', 20) }}
                </span>
                <span v-else class="text-muted">—</span>
              </td>
              <td>
                <small class="text-muted">{{ formatDate(getArtifactCreatedAt(artifact)) }}</small>
              </td>
              <td v-if="canModifyArtifacts">
                <div class="d-flex gap-1">
                  <button
                    class="btn btn-sm btn-outline-danger"
                    title="Remove from release"
                    @click="removeArtifact(artifact)"
                  >
                    <i class="fas fa-times"></i>
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Pagination Controls -->
      <PaginationControls
        v-if="totalArtifactPages > 1"
        v-model:current-page="currentArtifactPage"
        v-model:page-size="artifactsPerPage"
        :total-pages="totalArtifactPages"
        :total-items="filteredDisplayArtifacts.length"
        :show-page-size-selector="true"
      />
    </div>

    <Teleport to="body">
      <!-- Add Artifact Modal -->
      <div
        v-if="canModifyArtifacts"
        id="addArtifactModal"
        class="modal fade"
        tabindex="-1"
        role="dialog"
        aria-modal="true"
      >
        <div class="modal-dialog modal-lg">
          <div class="modal-content">
            <div class="modal-header">
              <h5 class="modal-title">Add Artifact to Release</h5>
              <button
                type="button"
                class="btn-close"
                data-bs-dismiss="modal"
              ></button>
            </div>
            <div class="modal-body">
            <!-- Search and Filter Controls -->
            <div class="mb-3">
              <div class="row g-2">
                <div class="col-md-6">
                  <div class="input-group">
                    <span class="input-group-text">
                      <i class="fas fa-search"></i>
                    </span>
                    <input
                      v-model="searchQuery"
                      type="text"
                      class="form-control"
                      placeholder="Search artifacts by name, component, or format..."
                    >
                  </div>
                </div>
                <div class="col-md-3">
                  <select v-model="filterType" class="form-select">
                    <option value="">All Types</option>
                    <option value="sbom">SBOMs Only</option>
                    <option value="document">Documents Only</option>
                  </select>
                </div>
                <div class="col-md-3">
                  <select v-model="filterComponent" class="form-select">
                    <option value="">All Components</option>
                    <option v-for="component in uniqueComponents" :key="component" :value="component">
                      {{ component }}
                    </option>
                  </select>
                </div>
              </div>
            </div>

            <!-- Results Summary -->
            <div v-if="!isLoadingArtifacts" class="d-flex justify-content-between align-items-center mb-3">
              <small class="text-muted">
                Showing {{ filteredArtifacts.length }} of {{ availableArtifacts.length }} artifacts
                <span v-if="selectedArtifacts.length > 0">
                  ({{ selectedArtifacts.length }} selected)
                </span>
              </small>
              <div class="btn-group btn-group-sm">
                <button
                  type="button"
                  class="btn btn-outline-primary"
                  :disabled="filteredArtifacts.length === 0"
                  @click="selectAllFiltered"
                >
                  Select All
                </button>
                <button
                  type="button"
                  class="btn btn-outline-secondary"
                  :disabled="selectedArtifacts.length === 0"
                  @click="clearSelection"
                >
                  Clear
                </button>
              </div>
            </div>

            <!-- Loading State -->
            <div v-if="isLoadingArtifacts" class="text-center py-4">
              <div class="spinner-border spinner-border-sm text-primary" role="status">
                <span class="visually-hidden">Loading...</span>
              </div>
              <div class="ms-2">Loading artifacts...</div>
            </div>

            <!-- No Results -->
            <div v-else-if="availableArtifacts.length === 0" class="text-center py-4 text-muted">
              <i class="fas fa-inbox fa-2x mb-2 opacity-50"></i>
              <div>No available artifacts to add</div>
            </div>

            <!-- No Filtered Results -->
            <div v-else-if="filteredArtifacts.length === 0" class="text-center py-4 text-muted">
              <i class="fas fa-search fa-2x mb-2 opacity-50"></i>
              <div>No artifacts match your search criteria</div>
              <button class="btn btn-link btn-sm mt-2" @click="clearFilters">Clear filters</button>
            </div>

            <!-- Artifacts Table -->
            <div v-else class="artifacts-table-container">
              <div class="table-responsive" style="max-height: 400px; overflow-y: auto;">
                <table class="table table-hover table-sm">
                  <thead class="table-light sticky-top">
                    <tr>
                      <th style="width: 40px;">
                        <input
                          ref="selectAllCheckbox"
                          type="checkbox"
                          class="form-check-input"
                          :checked="allFilteredSelected"
                          @change="toggleAllFiltered"
                        >
                      </th>
                      <th style="width: 40px;">Type</th>
                      <th>Name</th>
                      <th>Component</th>
                      <th>Format/Type</th>
                      <th>Version</th>
                      <th style="width: 100px;">Created</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr
                      v-for="artifact in paginatedArtifacts"
                      :key="`${artifact.artifact_type}-${artifact.id}`"
                      class="artifact-table-row"
                      :class="{ 'table-active': isArtifactSelected(artifact) }"
                      @click="toggleArtifactSelection(artifact, $event)"
                    >
                      <td>
                        <input
                          type="checkbox"
                          class="form-check-input"
                          :checked="isArtifactSelected(artifact)"
                          @click.stop
                          @change="toggleArtifactSelection(artifact, $event)"
                        >
                      </td>
                      <td>
                        <span class="artifact-type-icon" :class="getAvailableArtifactIconClass(artifact)">
                          <i :class="getAvailableArtifactIcon(artifact)" class="fa-sm"></i>
                        </span>
                      </td>
                      <td>
                        <div class="artifact-name-cell">
                          <div class="fw-medium">{{ artifact.name }}</div>
                          <div v-if="artifact.artifact_type === 'sbom' && artifact.version" class="text-muted small version-display" :title="artifact.version">
                            {{ truncateText(artifact.version, 20) }}
                          </div>
                        </div>
                      </td>
                      <td>
                        <span class="component-link">{{ artifact.component.name }}</span>
                      </td>
                      <td>
                        <span class="format-text">{{ getAvailableArtifactFormat(artifact) }}</span>
                      </td>
                      <td>
                        <span v-if="artifact.version" class="version-text version-display" :title="artifact.version">{{ truncateText(artifact.version, 20) }}</span>
                        <span v-else class="text-muted">—</span>
                      </td>
                      <td>
                        <small class="text-muted">{{ formatDate(artifact.created_at) }}</small>
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
          </div>
            <div class="modal-footer">
              <button
                type="button"
                class="btn btn-secondary"
                data-bs-dismiss="modal"
              >
                Cancel
              </button>
              <button
                type="button"
                class="btn btn-primary"
                :disabled="selectedArtifacts.length === 0 || isSubmitting"
                @click="addSelectedArtifacts"
              >
                <span v-if="isSubmitting" class="spinner-border spinner-border-sm me-2"></span>
                Add {{ selectedArtifacts.length }} Artifact{{ selectedArtifacts.length === 1 ? '' : 's' }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </Teleport>
  </StandardCard>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch, nextTick } from 'vue'
import $axios from '../utils'
import { showError, showSuccess } from '../alerts'
import { isAxiosError } from 'axios'
import StandardCard from './StandardCard.vue'
import PaginationControls from './PaginationControls.vue'
import { useUrlGeneration } from '../composables/useUrlGeneration'

interface Artifact {
  id: string
  sbom?: {
    id: string
    name: string
    format: string
    format_version: string
    version?: string
    created_at: string
    component: {
      id: string
      name: string
    }
  }
  document?: {
    id: string
    name: string
    document_type: string
    version?: string
    created_at: string
    component: {
      id: string
      name: string
    }
  }
}

interface AvailableArtifact {
  id: string
  artifact_type: 'sbom' | 'document'
  name: string
  version?: string
  format?: string
  format_version?: string
  document_type?: string
  created_at: string
  component: {
    id: string
    name: string
    component_type: string
  }
}

interface Props {
  releaseId: string
  productId: string
  hasCrudPermissions?: boolean | string
  isLatestRelease?: boolean | string
}

const props = withDefaults(defineProps<Props>(), {
  hasCrudPermissions: false,
  isLatestRelease: false
})

// Detect if we're on a public view or custom domain from the current URL
const isPublicView = window.location.pathname.includes('/public/')

const getIsCustomDomain = () => {
  // Check if we're on a custom domain (not the main app domain)
  // This is a simple heuristic - in production, this might need to be more sophisticated
  const hostname = window.location.hostname
  // Exclude localhost and main app domains
  return !hostname.includes('localhost') && !hostname.includes('.sbomify')
}
const isCustomDomain = getIsCustomDomain()

// Use URL generation composable
// Note: These values are based on window.location which doesn't change during component lifecycle
const { getSbomDetailUrl, getDocumentDetailUrl, getComponentUrl: getComponentUrlFromComposable } = useUrlGeneration(
  isPublicView,
  isCustomDomain
)

// State
const artifacts = ref<Artifact[]>([])
const availableArtifacts = ref<AvailableArtifact[]>([])
const selectedArtifacts = ref<AvailableArtifact[]>([])
const isLoading = ref(false)
const isLoadingArtifacts = ref(false)
const isSubmitting = ref(false)
const error = ref<string | null>(null)
const selectAllCheckbox = ref<HTMLInputElement | null>(null)

// Search and Filter State
const searchQuery = ref('')
const filterType = ref('')
const filterComponent = ref('')
const currentPage = ref(1)
const itemsPerPage = ref(50)

// Artifacts Table State
const artifactsSearchQuery = ref('')
const artifactsFilterType = ref('')
const artifactsFilterComponent = ref('')
const artifactsPerPage = ref(25)
const currentArtifactPage = ref(1)

// Computed
const hasCrudPermissions = computed(() => {
  if (typeof props.hasCrudPermissions === 'string') {
    return props.hasCrudPermissions === 'true'
  }
  return props.hasCrudPermissions
})

const isLatestRelease = computed(() => {
  if (typeof props.isLatestRelease === 'string') {
    return props.isLatestRelease === 'true'
  }
  return props.isLatestRelease
})

const canModifyArtifacts = computed(() => {
  return hasCrudPermissions.value && !isLatestRelease.value
})

const hasData = computed(() => artifacts.value.length > 0)

const uniqueComponents = computed(() => {
  const components = new Set(availableArtifacts.value.map(artifact => artifact.component.name))
  return Array.from(components).sort()
})

const filteredArtifacts = computed(() => {
  let filtered = availableArtifacts.value

  // Apply search filter
  if (searchQuery.value.trim()) {
    const query = searchQuery.value.toLowerCase().trim()
    filtered = filtered.filter(artifact =>
      artifact.name.toLowerCase().includes(query) ||
      artifact.component.name.toLowerCase().includes(query) ||
      getAvailableArtifactFormat(artifact).toLowerCase().includes(query) ||
      (artifact.version && artifact.version.toLowerCase().includes(query))
    )
  }

  // Apply type filter
  if (filterType.value) {
    filtered = filtered.filter(artifact => artifact.artifact_type === filterType.value)
  }

  // Apply component filter
  if (filterComponent.value) {
    filtered = filtered.filter(artifact => artifact.component.name === filterComponent.value)
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

const allFilteredSelected = computed(() => {
  return filteredArtifacts.value.length > 0 &&
         filteredArtifacts.value.every(artifact => isArtifactSelected(artifact))
})

const someFilteredSelected = computed(() => {
  return filteredArtifacts.value.some(artifact => isArtifactSelected(artifact)) &&
         !allFilteredSelected.value
})

// Artifacts Table Computed Properties
const uniqueArtifactComponents = computed(() => {
  const components = new Set(artifacts.value.map(artifact => getComponentName(artifact)))
  return Array.from(components).sort()
})

const filteredDisplayArtifacts = computed(() => {
  let filtered = artifacts.value

  // Apply search filter
  if (artifactsSearchQuery.value.trim()) {
    const query = artifactsSearchQuery.value.toLowerCase().trim()
    filtered = filtered.filter(artifact =>
      getArtifactName(artifact).toLowerCase().includes(query) ||
      getComponentName(artifact).toLowerCase().includes(query) ||
      getArtifactFormat(artifact).toLowerCase().includes(query) ||
      (getArtifactVersion(artifact) && getArtifactVersion(artifact)!.toLowerCase().includes(query))
    )
  }

  // Apply type filter
  if (artifactsFilterType.value) {
    filtered = filtered.filter(artifact => {
      if (artifactsFilterType.value === 'sbom') {
        return artifact.sbom
      } else if (artifactsFilterType.value === 'document') {
        return artifact.document
      }
      return true
    })
  }

  // Apply component filter
  if (artifactsFilterComponent.value) {
    filtered = filtered.filter(artifact => getComponentName(artifact) === artifactsFilterComponent.value)
  }

  return filtered
})

const totalArtifactPages = computed(() => {
  return Math.ceil(filteredDisplayArtifacts.value.length / artifactsPerPage.value)
})

const paginatedFilteredArtifacts = computed(() => {
  const start = (currentArtifactPage.value - 1) * artifactsPerPage.value
  const end = start + artifactsPerPage.value
  return filteredDisplayArtifacts.value.slice(start, end)
})

// Methods
const formatDate = (dateString: string): string => {
  return new Date(dateString).toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric'
  })
}

const truncateText = (text: string, maxLength: number): string => {
  if (text.length <= maxLength) return text
  return text.substring(0, maxLength - 3) + '...'
}

// Selection Methods
const isArtifactSelected = (artifact: AvailableArtifact): boolean => {
  return selectedArtifacts.value.some(selected =>
    selected.id === artifact.id && selected.artifact_type === artifact.artifact_type
  )
}

const toggleArtifactSelection = (artifact: AvailableArtifact, event?: Event) => {
  if (event && (event.target as HTMLInputElement).type === 'checkbox') {
    // Handle checkbox click
    const isChecked = (event.target as HTMLInputElement).checked
    if (isChecked && !isArtifactSelected(artifact)) {
      selectedArtifacts.value.push(artifact)
    } else if (!isChecked && isArtifactSelected(artifact)) {
      selectedArtifacts.value = selectedArtifacts.value.filter(selected =>
        !(selected.id === artifact.id && selected.artifact_type === artifact.artifact_type)
      )
    }
  } else {
    // Handle row click
    if (isArtifactSelected(artifact)) {
      selectedArtifacts.value = selectedArtifacts.value.filter(selected =>
        !(selected.id === artifact.id && selected.artifact_type === artifact.artifact_type)
      )
    } else {
      selectedArtifacts.value.push(artifact)
    }
  }
}

const selectAllFiltered = () => {
  filteredArtifacts.value.forEach(artifact => {
    if (!isArtifactSelected(artifact)) {
      selectedArtifacts.value.push(artifact)
    }
  })
}

const clearSelection = () => {
  selectedArtifacts.value = []
}

const toggleAllFiltered = (event: Event) => {
  const isChecked = (event.target as HTMLInputElement).checked
  if (isChecked) {
    selectAllFiltered()
  } else {
    // Remove all filtered artifacts from selection
    const filteredIds = new Set(filteredArtifacts.value.map(a => `${a.artifact_type}-${a.id}`))
    selectedArtifacts.value = selectedArtifacts.value.filter(selected =>
      !filteredIds.has(`${selected.artifact_type}-${selected.id}`)
    )
  }
}

// Filter Methods
const clearFilters = () => {
  searchQuery.value = ''
  filterType.value = ''
  filterComponent.value = ''
  currentPage.value = 1
}

const getArtifactName = (artifact: Artifact): string => {
  return artifact.sbom?.name || artifact.document?.name || 'Unknown'
}

const getArtifactType = (artifact: Artifact): string => {
  if (artifact.sbom) return 'SBOM'
  if (artifact.document) return 'Document'
  return 'Unknown'
}

const getArtifactFormat = (artifact: Artifact): string => {
  if (artifact.sbom) {
    const formatDisplay = artifact.sbom.format === 'cyclonedx' ? 'CycloneDX' : artifact.sbom.format.toUpperCase()
    return `${formatDisplay} ${artifact.sbom.format_version}`
  }
  if (artifact.document) {
    return artifact.document.document_type.charAt(0).toUpperCase() + artifact.document.document_type.slice(1)
  }
  return 'Unknown'
}

const getArtifactVersion = (artifact: Artifact): string | null => {
  return artifact.sbom?.version || artifact.document?.version || null
}

const getArtifactCreatedAt = (artifact: Artifact): string => {
  return artifact.sbom?.created_at || artifact.document?.created_at || ''
}

const getComponentName = (artifact: Artifact): string => {
  return artifact.sbom?.component.name || artifact.document?.component.name || 'Unknown'
}

const getComponentUrl = (artifact: Artifact): string => {
  const componentId = artifact.sbom?.component.id || artifact.document?.component.id
  if (!componentId) return '#'
  return getComponentUrlFromComposable(componentId)
}

const getArtifactUrl = (artifact: Artifact): string => {
  if (artifact.sbom) {
    const sbomId = artifact.sbom.id
    const componentId = artifact.sbom.component?.id
    if (!sbomId || !componentId) {
      return '#'
    }
    return getSbomDetailUrl(sbomId, componentId)
  }
  if (artifact.document) {
    const documentId = artifact.document.id
    const componentId = artifact.document.component?.id
    if (!documentId || !componentId) {
      return '#'
    }
    return getDocumentDetailUrl(documentId, componentId)
  }
  return '#'
}

const getArtifactIcon = (artifact: Artifact): string => {
  if (artifact.sbom) return 'fas fa-file-code'
  if (artifact.document) return 'fas fa-file-alt'
  return 'fas fa-file'
}

const getArtifactIconClass = (artifact: Artifact): string => {
  if (artifact.sbom) return 'sbom-icon'
  if (artifact.document) return 'document-icon'
  return 'default-icon'
}

const getArtifactBadgeClass = (artifact: Artifact): string => {
  if (artifact.sbom) return 'badge bg-success-subtle text-success'
  if (artifact.document) return 'badge bg-warning-subtle text-warning'
  return 'badge bg-secondary-subtle text-secondary'
}

// Available artifact methods
const getAvailableArtifactIcon = (artifact: AvailableArtifact): string => {
  if (artifact.artifact_type === 'sbom') return 'fas fa-file-code'
  if (artifact.artifact_type === 'document') return 'fas fa-file-alt'
  return 'fas fa-file'
}

const getAvailableArtifactIconClass = (artifact: AvailableArtifact): string => {
  if (artifact.artifact_type === 'sbom') return 'sbom-icon'
  if (artifact.artifact_type === 'document') return 'document-icon'
  return 'default-icon'
}



const getAvailableArtifactFormat = (artifact: AvailableArtifact): string => {
  if (artifact.artifact_type === 'sbom' && artifact.format && artifact.format_version) {
    const formatDisplay = artifact.format === 'cyclonedx' ? 'CycloneDX' : artifact.format.toUpperCase()
    return `${formatDisplay} ${artifact.format_version}`
  }
  if (artifact.artifact_type === 'document' && artifact.document_type) {
    return artifact.document_type.charAt(0).toUpperCase() + artifact.document_type.slice(1)
  }
  return 'Unknown'
}

const loadArtifacts = async () => {
  isLoading.value = true
  error.value = null

  try {
    // Get artifacts already in this release
    const response = await $axios.get(`/api/v1/releases/${props.releaseId}/artifacts?mode=existing`)

    // Handle both old array format and new paginated format for backward compatibility
    const artifactsData = Array.isArray(response.data) ? response.data : response.data.items || []

    // Transform the response to match expected format
    artifacts.value = artifactsData.map((artifact: {
      id: string
      artifact_type: string
      sbom_id?: string
      document_id?: string
      artifact_name: string
      sbom_format?: string
      sbom_format_version?: string
      sbom_version?: string
      document_type?: string
      document_version?: string
      created_at: string
      component_id: string
      component_name: string
      [key: string]: unknown // Allow other properties but ensure required ones are typed
    }): Artifact | null => {
      if (artifact.artifact_type === 'sbom') {
        const sbomId = artifact.sbom_id
        return {
            id: artifact.id,
            sbom: {
              id: sbomId || '',
              name: artifact.artifact_name,
              // Ensure required string fields are always populated
              format: (() => {
                const format = artifact.sbom_format
                if (!format) console.warn(`Missing SBOM format for artifact ${artifact.id}`)
                return format ?? 'unknown'
              })(),
              format_version: (() => {
                const version = artifact.sbom_format_version
                if (!version) console.warn(`Missing SBOM format version for artifact ${artifact.id}`)
                return version ?? 'unknown'
              })(),
              version: artifact.sbom_version,
              created_at: artifact.created_at,
              component: {
                id: artifact.component_id,
                name: artifact.component_name
            }
          }
        }
      } else if (artifact.artifact_type === 'document') {
        const documentId = artifact.document_id
        return {
            id: artifact.id,
            document: {
              id: documentId || '',
              name: artifact.artifact_name,
              // Default to a placeholder when API omits the type
              document_type: (() => {
                const type = artifact.document_type
                if (!type) console.warn(`Missing document type for artifact ${artifact.id}`)
                return type ?? 'unknown'
              })(),
              version: artifact.document_version,
              created_at: artifact.created_at,
              component: {
                id: artifact.component_id,
                name: artifact.component_name
            }
          }
        }
      } else {
        return null
      }
    }).filter((artifact: Artifact | null): artifact is Artifact => artifact !== null)
  } catch (err) {
    console.error('Error loading artifacts:', err)
    error.value = 'Failed to load artifacts'

    if (isAxiosError(err)) {
      showError(err.response?.data?.detail || 'Failed to load artifacts')
    } else {
      showError('Failed to load artifacts')
    }
  } finally {
    isLoading.value = false
  }
}

const loadAvailableArtifacts = async () => {
  isLoadingArtifacts.value = true

  try {
    // Get available artifacts that can be added to this release
    const response = await $axios.get(`/api/v1/releases/${props.releaseId}/artifacts?mode=available`)
    // Handle both old array format and new paginated format for backward compatibility
    if (Array.isArray(response.data)) {
      availableArtifacts.value = response.data
    } else {
      availableArtifacts.value = response.data.items || []
    }
  } catch (err) {
    console.error('Error loading available artifacts:', err)

    if (isAxiosError(err)) {
      showError(err.response?.data?.detail || 'Failed to load available artifacts')
    } else {
      showError('Failed to load available artifacts')
    }
  } finally {
    isLoadingArtifacts.value = false
  }
}

const showAddArtifactModal = async () => {
  await loadAvailableArtifacts()
  selectedArtifacts.value = []
  // Reset filters and pagination
  searchQuery.value = ''
  filterType.value = ''
  filterComponent.value = ''
  currentPage.value = 1

  const modalElement = document.getElementById('addArtifactModal')
  if (modalElement) {
    const bootstrap = (window as unknown as { bootstrap?: { Modal: new(element: Element) => { show(): void } } }).bootstrap
    if (bootstrap && bootstrap.Modal) {
      const modal = new bootstrap.Modal(modalElement)
      modal.show()
    }
  }
}

const addSelectedArtifacts = async () => {
  if (selectedArtifacts.value.length === 0) return

  isSubmitting.value = true

  try {
    const results = []

    // Add each selected artifact to the release
    for (const artifact of selectedArtifacts.value) {
      try {
        let payload: Record<string, string> = {}

        if (artifact.artifact_type === 'sbom') {
          payload.sbom_id = String(artifact.id)
        } else {
          payload.document_id = String(artifact.id)
        }

        const response = await $axios.post(`/api/v1/releases/${props.releaseId}/artifacts`, payload)
        results.push({ success: true, artifact, response: response.data })
      } catch (err) {
        console.error(`Error adding artifact ${artifact.name}:`, err)
        // Log the specific error details for debugging
        if (isAxiosError(err) && err.response) {
          console.error(`API Error Details:`, err.response.data)
          console.error(`Status: ${err.response.status}`)
        }
        results.push({ success: false, artifact, error: err })
      }
    }

    // Count successes and failures
    const successful = results.filter(r => r.success)
    const failed = results.filter(r => !r.success)

    if (successful.length > 0) {
      showSuccess(`Successfully added ${successful.length} artifact${successful.length === 1 ? '' : 's'} to the release`)
      await loadArtifacts() // Reload artifacts to show the new ones
    }

    if (failed.length > 0) {
      const errorMessages = failed.map(f => {
        if (isAxiosError(f.error)) {
          const errorDetail = f.error.response?.data?.detail || 'Unknown error'

          // Provide more user-friendly error messages for common cases
          if (errorDetail.includes('latest')) {
            return `${f.artifact.name}: Cannot add artifacts to the 'latest' release`
          } else if (errorDetail.includes('team')) {
            return `${f.artifact.name}: This artifact doesn't belong to your workspace`
          } else if (errorDetail.includes('already exists')) {
            return `${f.artifact.name}: This artifact is already in the release`
          } else if (errorDetail.includes('already contains')) {
            return `${f.artifact.name}: Release already contains this type of artifact from the same component`
          }

          return `${f.artifact.name}: ${errorDetail}`
        }
        return `${f.artifact.name}: Failed to add`
      })
      showError(`Failed to add ${failed.length} artifact${failed.length === 1 ? '' : 's'}:\n${errorMessages.join('\n')}`)
    }

    // Close modal after attempting to add artifacts
    const modalElement = document.getElementById('addArtifactModal')
    if (modalElement) {
      const bootstrap = (window as unknown as { bootstrap?: { Modal: new(element: Element) => { hide(): void } } }).bootstrap
      if (bootstrap && bootstrap.Modal) {
        const modal = new bootstrap.Modal(modalElement)
        modal.hide()
      }
    }

  } catch (err) {
    console.error('Error adding artifacts:', err)
    showError('Failed to add artifacts')
  } finally {
    isSubmitting.value = false
  }
}

const removeArtifact = async (artifact: Artifact) => {
  if (!confirm(`Are you sure you want to remove "${getArtifactName(artifact)}" from this release?`)) {
    return
  }

  try {
    await $axios.delete(`/api/v1/releases/${props.releaseId}/artifacts/${artifact.id}`)
    showSuccess(`Successfully removed ${getArtifactName(artifact)} from the release`)
    await loadArtifacts() // Reload artifacts to reflect the removal
  } catch (err) {
    console.error('Error removing artifact:', err)
    if (isAxiosError(err)) {
      showError(err.response?.data?.detail || 'Failed to remove artifact')
    } else {
      showError('Failed to remove artifact')
    }
  }
}

// Lifecycle
onMounted(async () => {
  await loadArtifacts()
})

// Watch for filter changes to reset pagination
watch([searchQuery, filterType, filterComponent], () => {
  currentPage.value = 1
})

// Watch for artifacts filter changes to reset pagination
watch([artifactsSearchQuery, artifactsFilterType, artifactsFilterComponent], () => {
  currentArtifactPage.value = 1
})

// Watch for selection changes to update checkbox indeterminate state
watch([someFilteredSelected], () => {
  nextTick(() => {
    if (selectAllCheckbox.value) {
      selectAllCheckbox.value.indeterminate = someFilteredSelected.value
    }
  })
})

// Expose methods for external use
defineExpose({
  loadArtifacts
})
</script>

<style scoped>
.dashboard-empty {
  text-align: center;
  padding: 3rem 1rem;
  color: #6c757d;
}

.empty-icon {
  font-size: 3rem;
  margin-bottom: 1rem;
  opacity: 0.3;
}

/* Artifacts Table Styles */
.artifacts-table-container {
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: white;
  overflow: hidden;
}

.table-controls {
  padding: 1rem;
  background: #f8fafc;
  border-bottom: 1px solid #e2e8f0;
}

.artifact-row {
  transition: background-color 0.15s ease;
}

.artifact-row:hover {
  background-color: #f8fafc;
}

.artifact-type-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 6px;
  font-size: 0.75rem;
}

.artifact-type-icon.sbom-icon {
  background: linear-gradient(135deg, #10b981, #059669);
  color: white;
}

.artifact-type-icon.document-icon {
  background: linear-gradient(135deg, #f59e0b, #d97706);
  color: white;
}

.artifact-type-icon.default-icon {
  background: linear-gradient(135deg, #6b7280, #4b5563);
  color: white;
}

.artifact-name-cell {
  min-width: 200px;
}

.artifact-name-link {
  color: #1a202c;
  text-decoration: none;
}

.artifact-name-link:hover {
  color: #6366f1;
  text-decoration: underline;
}

.artifact-type-badge {
  font-size: 0.75rem;
  font-weight: 500;
}

.component-link {
  color: #3b82f6;
  text-decoration: none;
}

.component-link:hover {
  text-decoration: underline;
}

.format-text {
  font-family: monospace;
  font-size: 0.875rem;
  background: #f1f5f9;
  padding: 2px 6px;
  border-radius: 4px;
}

.version-text {
  font-family: monospace;
  font-size: 0.875rem;
}

.modal .artifacts-list {
  max-height: 400px;
  overflow-y: auto;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 0.5rem;
}

.modal .artifact-item {
  border: 1px solid #f1f5f9;
  border-radius: 8px;
  padding: 1rem;
  margin-bottom: 0.5rem;
  transition: all 0.2s ease;
}

.modal .artifact-item:hover {
  border-color: #e2e8f0;
  background-color: #f8fafc;
}

.modal .artifact-item:last-child {
  margin-bottom: 0;
}

.modal .artifact-header {
  display: flex;
  align-items: flex-start;
  gap: 0.75rem;
}

.artifact-icon-small {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1rem;
  flex-shrink: 0;
}

.artifact-details {
  flex: 1;
}

.artifact-title-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.25rem;
}

.artifact-meta-small {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  margin-bottom: 0.25rem;
  font-size: 0.8rem;
  color: #64748b;
}

.component-name {
  color: #6366f1;
}

.artifact-format {
  color: #059669;
}

.artifact-version {
  color: #d97706;
  font-weight: 500;
}

.artifact-date {
  font-size: 0.75rem;
  color: #9ca3af;
}

.component-item {
  padding: 0.75rem;
  border-radius: 6px;
  transition: background-color 0.2s ease;
}

.component-item:hover {
  background-color: #f8fafc;
}

.component-info {
  margin-left: 0.5rem;
}

.component-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.25rem;
}

.component-name {
  font-weight: 500;
  color: #1a202c;
}

.component-type-badge {
  font-size: 0.75rem;
  font-weight: 500;
}

.component-details {
  font-size: 0.875rem;
  color: #64748b;
}

.form-check-label {
  cursor: pointer;
}

.badge {
  font-size: 0.75rem;
  font-weight: 500;
}

.btn-sm {
  padding: 0.375rem 0.75rem;
  font-size: 0.875rem;
}

.version-display {
  display: inline-block;
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: bottom;
}

input.editable-field[type="date"] {
  font-size: 16pt; /* Slightly smaller for date inputs */
  padding: 4px 0;
}

/* Artifact Selection Table Styles */
.artifacts-table-container {
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: white;
}

.artifact-table-row {
  cursor: pointer;
  transition: background-color 0.15s ease;
}

.artifact-table-row:hover {
  background-color: #f8fafc !important;
}

.artifact-table-row.table-active {
  background-color: #eff6ff !important;
}

.artifact-type-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 6px;
  font-size: 0.75rem;
}

.artifact-type-icon.sbom-icon {
  background: linear-gradient(135deg, #10b981, #059669);
  color: white;
}

.artifact-type-icon.document-icon {
  background: linear-gradient(135deg, #f59e0b, #d97706);
  color: white;
}

.artifact-type-icon.default-icon {
  background: linear-gradient(135deg, #6b7280, #4b5563);
  color: white;
}

.artifact-name-cell {
  min-width: 200px;
}

.component-link {
  color: #3b82f6;
  text-decoration: none;
}

.component-link:hover {
  text-decoration: underline;
}

.format-text {
  font-family: monospace;
  font-size: 0.875rem;
  background: #f1f5f9;
  padding: 2px 6px;
  border-radius: 4px;
}

.version-text {
  font-family: monospace;
  font-size: 0.875rem;
}

.table-responsive {
  border-radius: 8px;
}

.table-light th {
  background-color: #f8fafc;
  border-color: #e2e8f0;
  font-weight: 600;
  font-size: 0.875rem;
}

.sticky-top {
  position: sticky;
  top: 0;
  z-index: 10;
}

@media (max-width: 768px) {
  .artifact-header {
    flex-direction: column;
    gap: 0.75rem;
  }

  .artifact-actions {
    align-self: flex-start;
  }

  .meta-row {
    flex-direction: column;
    align-items: flex-start;
    gap: 0.25rem;
  }
}
</style>
