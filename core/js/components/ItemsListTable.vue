<template>
  <StandardCard
    :title="title"
    variant="default"
    shadow="sm"
  >
    <template #header-actions>
      <button
        v-if="hasCrudPermissions && showAddButton"
        class="btn btn-primary px-4"
        data-bs-toggle="modal"
        :data-bs-target="`#add${capitalizedItemType}Modal`"
      >
        Add {{ capitalizedItemType }}
      </button>
    </template>

    <!-- Loading State -->
    <div v-if="isLoading" class="dashboard-empty">
      <div class="spinner-border text-primary" role="status">
        <span class="visually-hidden">Loading...</span>
      </div>
      <p class="mb-0 mt-2">Loading {{ itemType }}s...</p>
    </div>

    <!-- Error State -->
    <div v-else-if="error" class="alert alert-danger">
      <p class="mb-0">Failed to load {{ itemType }}s. Please try refreshing the page.</p>
    </div>

    <!-- Empty State -->
    <div v-else-if="!hasData" class="dashboard-empty">
      <p class="mb-0">No {{ itemType }}s added</p>
    </div>

    <!-- Data Table -->
    <div v-else class="table-responsive">
      <table class="table dashboard-table">
        <thead>
          <tr>
            <th>Name</th>
            <th v-if="itemType === 'component'">Type</th>
            <th>{{ getRelationshipColumnHeader() }}</th>
            <th class="text-center">Public?</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in items" :key="item.id">
            <td>
              <a
                :href="getItemDetailUrl(item)"
                class="text-primary text-decoration-none"
              >
                {{ item.name }}
              </a>
            </td>
            <td v-if="itemType === 'component'">
              <span class="badge bg-info-subtle text-info">
                {{ getComponentTypeDisplayName((item as Component).component_type) }}
              </span>
            </td>
            <td>
               <div v-if="itemType === 'product'">
                 <span v-if="(item as Product).projects.length === 0" class="text-muted">
                   No projects
                 </span>
                 <div v-else>
                   <a
                     v-for="project in (item as Product).projects"
                     :key="project.id"
                     :href="`/project/${project.id}/`"
                     title="Details"
                     class="icon-link me-1 mb-1"
                     style="text-decoration: none;"
                   >
                     <span class="badge bg-secondary-subtle text-secondary">
                       {{ project.name }}
                     </span>
                   </a>
                 </div>
               </div>

               <div v-else-if="itemType === 'project'">
                 <span v-if="(item as Project).components.length === 0" class="text-muted">
                   No components
                 </span>
                 <div v-else>
                   <a
                     v-for="component in (item as Project).components"
                     :key="component.id"
                     :href="`/component/${component.id}/`"
                     title="Details"
                     class="icon-link me-1 mb-1"
                     style="text-decoration: none;"
                   >
                     <span class="badge bg-secondary-subtle text-secondary">
                       {{ component.name }}
                       <small class="ms-1 text-muted">({{ getComponentTypeDisplayName(component.component_type) }})</small>
                     </span>
                   </a>
                 </div>
               </div>

               <div v-else-if="itemType === 'component'">
                 <span v-if="(item as Component).component_type === 'sbom'">
                   {{ getSbomCountText(item as Component) }}
                 </span>
                 <span v-else-if="(item as Component).component_type === 'document'" class="text-muted">
                   Document
                 </span>
                 <span v-else class="text-muted">
                   -
                 </span>
               </div>

               <span v-else>-</span>
             </td>
            <td class="text-center">
              <span
                v-if="item.is_public"
                class="badge bg-success-subtle text-success"
              >
                Public
              </span>
              <span
                v-else
                class="badge bg-secondary-subtle text-secondary"
              >
                Private
              </span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Pagination Controls -->
    <PaginationControls
      v-if="paginationMeta && paginationMeta.total_pages > 1"
      v-model:current-page="currentPage"
      v-model:page-size="pageSize"
      :total-pages="paginationMeta.total_pages"
      :total-items="paginationMeta.total"
      :show-page-size-selector="true"
    />
  </StandardCard>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import $axios from '../utils'
import { showError } from '../alerts'
import { isAxiosError } from 'axios'
import StandardCard from './StandardCard.vue'
import PaginationControls from './PaginationControls.vue'

// Types
interface BaseItem {
  id: string
  name: string
  is_public: boolean
  created_at?: string
}

interface Product extends BaseItem {
  projects: Array<{ id: string; name: string; is_public: boolean; component_type?: string }>
  project_count?: number
}

interface Project extends BaseItem {
  components: Array<{ id: string; name: string; is_public: boolean; component_type: string }>
  component_count?: number
}

interface Component extends BaseItem {
  component_type: string
  sbom_count?: number
}

type ItemData = Product | Project | Component

interface PaginationMeta {
  total: number
  page: number
  page_size: number
  total_pages: number
  has_previous: boolean
  has_next: boolean
}

interface PaginatedResponse {
  items: ItemData[]
  pagination: PaginationMeta
}

interface Props {
  itemType: 'product' | 'project' | 'component'
  title?: string
  apiEndpoint?: string
  hasCrudPermissions?: boolean | string
  showAddButton?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  title: '',
  apiEndpoint: '',
  hasCrudPermissions: false,
  showAddButton: true
})

// State
const items = ref<ItemData[]>([])
const isLoading = ref(false)
const error = ref<string | null>(null)
const paginationMeta = ref<PaginationMeta | null>(null)
const currentPage = ref(1)
const pageSize = ref(15)

// Computed
const hasCrudPermissions = computed(() => {
  if (typeof props.hasCrudPermissions === 'string') {
    return props.hasCrudPermissions === 'true'
  }
  return props.hasCrudPermissions
})

const capitalizedItemType = computed(() =>
  props.itemType.charAt(0).toUpperCase() + props.itemType.slice(1)
)

const hasData = computed(() => items.value.length > 0)

const computedTitle = computed(() =>
  props.title || capitalizedItemType.value + 's'
)

const computedApiEndpoint = computed(() =>
  props.apiEndpoint || `/api/v1/${props.itemType}s`
)

// Methods
const getItemDetailUrl = (item: ItemData): string => {
  return `/${props.itemType}/${item.id}/`
}

const getRelationshipColumnHeader = (): string => {
  switch (props.itemType) {
    case 'product':
      return 'Projects'
    case 'project':
      return 'Components'
    case 'component':
      return 'Content'
    default:
      return 'Related'
  }
}

const getComponentTypeDisplayName = (componentType: string): string => {
  switch (componentType) {
    case 'sbom':
      return 'SBOM'
    case 'document':
      return 'Document'
    default:
      return 'Unknown'
  }
}

const getSbomCountText = (component: Component): string => {
  const count = component.sbom_count || 0
  return count === 1 ? '1 SBOM' : `${count} SBOMs`
}

const loadItems = async () => {
  isLoading.value = true
  error.value = null

  try {
    const params = new URLSearchParams({
      page: currentPage.value.toString(),
      page_size: pageSize.value.toString()
    })

    const response = await $axios.get(`${computedApiEndpoint.value}?${params}`)

    if (response.status < 200 || response.status >= 300) {
      throw new Error(`HTTP ${response.status}`)
    }

    const data = response.data as PaginatedResponse
    items.value = data.items
    paginationMeta.value = data.pagination
  } catch (err) {
    console.error(`Error loading ${props.itemType}s:`, err)
    error.value = `Failed to load ${props.itemType}s`

    if (isAxiosError(err)) {
      showError(err.response?.data?.detail || `Failed to load ${props.itemType}s`)
    } else {
      showError(`Failed to load ${props.itemType}s`)
    }
  } finally {
    isLoading.value = false
  }
}

// Watchers for pagination changes
watch([currentPage, pageSize], () => {
  loadItems()
})

// Event listener setup for refresh events
const setupEventListeners = () => {
  if (window.eventBus && window.EVENTS) {
    let eventName: string | undefined

    switch (props.itemType) {
      case 'product':
        eventName = window.EVENTS.REFRESH_PRODUCTS
        break
      case 'project':
        eventName = window.EVENTS.REFRESH_PROJECTS
        break
      case 'component':
        eventName = window.EVENTS.REFRESH_COMPONENTS
        break
    }

    if (eventName) {
      window.eventBus.on(eventName, () => {
        currentPage.value = 1 // Reset to first page on refresh
        loadItems()
      })
      return true
    }
  }
  return false
}

// Lifecycle
onMounted(async () => {
  await loadItems()

  // Try to set up event listeners immediately, or wait for eventBus to be available
  if (!setupEventListeners()) {
    setTimeout(() => {
      setupEventListeners()
    }, 100)
  }
})

// Expose loadItems for external use
defineExpose({
  loadItems,
  title: computedTitle
})
</script>

<style scoped>
.dashboard-empty {
  text-align: center;
  padding: 3rem 1rem;
  color: #6c757d;
}

.dashboard-table {
  margin-bottom: 0;
}

.dashboard-table th {
  border-top: none;
  font-weight: 600;
  color: #495057;
  background-color: #f8f9fa;
}

.dashboard-table td {
  vertical-align: middle;
}

.icon-link {
  color: inherit;
  text-decoration: none;
}

.icon-link:hover {
  text-decoration: none;
}

.badge {
  font-size: 0.75rem;
  font-weight: 500;
}

.table-responsive {
  border-radius: 0.375rem;
}

/* Ensure proper spacing for relationship badges */
.badge + .badge {
  margin-left: 0.25rem;
}

@media (max-width: 768px) {
  .dashboard-table th:nth-child(2),
  .dashboard-table td:nth-child(2) {
    min-width: 120px;
  }
}
</style>