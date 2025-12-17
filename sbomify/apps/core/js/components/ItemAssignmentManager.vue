<template>
  <div class="item-assignment-manager">
    <div class="row g-4">
      <!-- Assigned Items -->
      <div class="col-lg-6">
        <StandardCard
          :title="getAssignedTitle()"
          variant="default"
          shadow="sm"
        >
          <template #header-actions>
            <span class="badge bg-primary rounded-pill">{{ assignedItems.length }}</span>
          </template>

          <!-- Search for assigned items -->
          <div class="search-container mb-3 border-bottom pb-3">
            <div class="input-group">
              <span class="input-group-text">
                <i class="fas fa-search text-muted"></i>
              </span>
              <input
                v-model="assignedSearch"
                type="text"
                class="form-control"
                :placeholder="`Search assigned ${childType}s...`"
              />
            </div>
          </div>

          <!-- Assigned items list -->
          <div class="assigned-items-container" style="max-height: 400px; overflow-y: auto">
            <div v-if="filteredAssignedItems.length === 0" class="text-center py-5 text-muted">
              <i class="fas fa-inbox fa-2x mb-3 d-block text-muted opacity-50"></i>
              <p class="mb-0">
                {{
                  assignedSearch
                    ? `No ${childType}s match your search`
                    : `No ${childType}s assigned yet`
                }}
              </p>
            </div>

            <div v-else>
              <div
                v-for="item in filteredAssignedItems"
                :key="item.id"
                class="item-card assigned-item"
              >
                <div class="d-flex align-items-center">
                  <div class="flex-grow-1 me-3">
                    <div class="item-header-wrapper d-flex justify-content-between align-items-center">
                      <div class="item-name-wrapper">
                        <h6 class="mb-1 text-break">
                          <a :href="getItemUrl(item)" class="text-decoration-none text-primary" @click.stop>
                            {{ item.name }}
                          </a>
                        </h6>
                        <small v-if="item.version" class="text-muted version-display" :title="item.version">{{ item.version }}</small>
                      </div>
                    <div class="d-flex align-items-center gap-2 item-badges">
                      <span v-if="item.is_public" class="badge bg-success-subtle text-success">
                        <i class="fas fa-globe me-1"></i>Public
                      </span>
                      <span v-else class="badge bg-secondary-subtle text-secondary">
                        <i class="fas fa-lock me-1"></i>Private
                      </span>
                      <span v-if="item.is_global" class="badge bg-primary-subtle text-primary">
                        Workspace
                      </span>
                    </div>
                  </div>
                </div>

                  <button
                    v-if="hasCrudPermissions"
                    class="btn btn-sm btn-outline-danger remove-item-btn"
                    :disabled="isLoading"
                    :title="`Remove ${item.name} from ${parentType}`"
                    @click.stop="removeSingleItem(item.id)"
                  >
                    <i class="fas fa-minus"></i>
                  </button>
                </div>
              </div>
            </div>
          </div>
        </StandardCard>
      </div>

      <!-- Available Items -->
      <div v-if="hasCrudPermissions" class="col-lg-6">
        <StandardCard
          title="Available Items"
          variant="default"
          shadow="sm"
        >
          <template #header-actions>
            <span class="badge bg-secondary rounded-pill">{{ availableItems.length }}</span>
          </template>

          <!-- Search for available items -->
          <div class="search-container mb-3 border-bottom pb-3">
            <div class="input-group">
              <span class="input-group-text">
                <i class="fas fa-search text-muted"></i>
              </span>
              <input
                v-model="availableSearch"
                type="text"
                class="form-control"
                :placeholder="`Search available ${childType}s...`"
              />
            </div>
          </div>

          <!-- Available items list -->
          <div
            class="available-items-container drop-zone"
            :class="{ 'drag-over': isDragOver && dragSource === 'available' }"
            style="max-height: 400px; overflow-y: auto"
            @dragover.prevent="handleDragOver"
            @dragleave="handleDragLeave"
            @drop="handleDrop"
          >
            <div v-if="filteredAvailableItems.length === 0" class="text-center py-5 text-muted">
              <i class="fas fa-plus-circle fa-2x mb-3 d-block text-muted opacity-50"></i>
              <p class="mb-0">
                {{
                  availableSearch
                    ? `No ${childType}s match your search`
                    : `No ${childType}s available to add`
                }}
              </p>
            </div>

            <div v-else>
              <div
                v-for="item in filteredAvailableItems"
                :key="item.id"
                class="item-card available-item"
                :class="{
                  dragging: draggedItem?.id === item.id,
                }"
                draggable="true"
                @dragstart="startDrag(item, 'available')"
                @dragend="endDrag"
              >
                <div class="d-flex align-items-center">
                  <div class="flex-grow-1 me-3">
                    <div class="item-header-wrapper d-flex justify-content-between align-items-center">
                      <div class="item-name-wrapper">
                        <h6 class="mb-1 text-break">
                          <a :href="getItemUrl(item)" class="text-decoration-none text-primary" @click.stop>
                            {{ item.name }}
                          </a>
                        </h6>
                        <small v-if="item.version" class="text-muted version-display" :title="item.version">{{ item.version }}</small>
                      </div>
                    <div class="d-flex align-items-center gap-2 item-badges">
                      <span v-if="item.is_public" class="badge bg-success-subtle text-success">
                        <i class="fas fa-globe me-1"></i>Public
                      </span>
                      <span v-else class="badge bg-secondary-subtle text-secondary">
                        <i class="fas fa-lock me-1"></i>Private
                      </span>
                      <span v-if="item.is_global" class="badge bg-primary-subtle text-primary">
                        Workspace
                      </span>
                    </div>
                  </div>
                </div>

                  <button
                    class="btn btn-sm btn-outline-primary add-item-btn"
                    :disabled="isLoading"
                    :title="`Add ${item.name} to ${parentType}`"
                    @click.stop="addSingleItem(item.id)"
                  >
                    <i class="fas fa-plus"></i>
                  </button>
                </div>
              </div>
            </div>
          </div>
        </StandardCard>
      </div>
    </div>

    <!-- Loading overlay -->
    <div v-if="isLoading" class="loading-overlay">
      <div class="d-flex align-items-center justify-content-center h-100">
        <div class="spinner-border text-primary" role="status">
          <span class="visually-hidden">Loading...</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
  import { ref, computed, onMounted } from 'vue'
  import $axios from '../../../core/js/utils'
  import { showSuccess, showError } from '../../../core/js/alerts'
  import { isAxiosError } from 'axios'
  import StandardCard from '../../../core/js/components/StandardCard.vue'

  interface AssignmentItem {
    id: string
    name: string
    version?: string
    is_public: boolean
    is_global?: boolean
    component_type?: string
  }

  const props = defineProps<{
    parentType: 'product' | 'project' // product assigns projects, project assigns components
    parentId: string
    hasCrudPermissions: boolean | string
    initialAssigned?: AssignmentItem[]
    initialAvailable?: AssignmentItem[]
  }>()

  // Convert string boolean to actual boolean
  const hasCrudPermissions = computed(() => {
    if (typeof props.hasCrudPermissions === 'string') {
      return props.hasCrudPermissions === 'true'
    }
    return props.hasCrudPermissions
  })

  // Determine child type based on parent type
  const childType = computed(() => (props.parentType === 'product' ? 'project' : 'component'))

  // State
  const isLoading = ref(false)
  const assignedItems = ref<AssignmentItem[]>(props.initialAssigned || [])
  const availableItems = ref<AssignmentItem[]>(props.initialAvailable || [])
  const assignedSearch = ref('')
  const availableSearch = ref('')

  // Drag and drop state (only for available -> assigned)
  const draggedItem = ref<AssignmentItem | null>(null)
  const dragSource = ref<'available' | null>(null)
  const isDragOver = ref(false)

  // Computed properties
  const filteredAssignedItems = computed(() =>
    assignedItems.value.filter(item =>
      item.name.toLowerCase().includes(assignedSearch.value.toLowerCase())
    )
  )

  const filteredAvailableItems = computed(() =>
    availableItems.value.filter(item =>
      item.name.toLowerCase().includes(availableSearch.value.toLowerCase())
    )
  )

  // Methods
  const getAssignedTitle = () => {
    if (props.parentType === 'product') return 'Product Projects'
    return 'Project Components'
  }

  const getItemUrl = (item: AssignmentItem) => {
    if (props.parentType === 'product') {
      // For products, we're managing projects
      return `/project/${item.id}/`
    } else {
      // For projects, we're managing components
      return `/component/${item.id}/`
    }
  }

  const addSingleItem = async (itemId: string) => {
    isLoading.value = true
    try {
      // Get current assigned IDs and add the single item
      const currentAssignedIds = assignedItems.value.map(item => item.id)
      const newAssignedIds = [...currentAssignedIds, itemId]

      const endpoint =
        props.parentType === 'product'
          ? `/api/v1/products/${props.parentId}`
          : `/api/v1/projects/${props.parentId}`

      const patchData =
        props.parentType === 'product'
          ? { project_ids: newAssignedIds }
          : { component_ids: newAssignedIds }

      await $axios.patch(endpoint, patchData)

      // Move item from available to assigned
      const itemToMove = availableItems.value.find(item => item.id === itemId)
      if (itemToMove) {
        assignedItems.value.push(itemToMove)
        availableItems.value = availableItems.value.filter(item => item.id !== itemId)
        showSuccess(`${itemToMove.name} added successfully`)
      }
    } catch (error) {
      console.error('Error adding item:', error)
      if (isAxiosError(error)) {
        showError(error.response?.data?.detail || `Failed to add ${childType.value}`)
      } else {
        showError(`Failed to add ${childType.value}`)
      }
    } finally {
      isLoading.value = false
    }
  }

  const removeSingleItem = async (itemId: string) => {
    isLoading.value = true
    try {
      // Get current assigned IDs and remove the single item
      const currentAssignedIds = assignedItems.value.map(item => item.id)
      const newAssignedIds = currentAssignedIds.filter(id => id !== itemId)

      const endpoint =
        props.parentType === 'product'
          ? `/api/v1/products/${props.parentId}`
          : `/api/v1/projects/${props.parentId}`

      const patchData =
        props.parentType === 'product'
          ? { project_ids: newAssignedIds }
          : { component_ids: newAssignedIds }

      await $axios.patch(endpoint, patchData)

      // Move item from assigned to available
      const itemToMove = assignedItems.value.find(item => item.id === itemId)
      if (itemToMove) {
        availableItems.value.push(itemToMove)
        assignedItems.value = assignedItems.value.filter(item => item.id !== itemId)
        showSuccess(`${itemToMove.name} removed successfully`)
      }
    } catch (error) {
      console.error('Error removing item:', error)
      if (isAxiosError(error)) {
        showError(error.response?.data?.detail || `Failed to remove ${childType.value}`)
      } else {
        showError(`Failed to remove ${childType.value}`)
      }
    } finally {
      isLoading.value = false
    }
  }

  // Drag and drop methods (only for available -> assigned)
  const startDrag = (item: AssignmentItem, source: 'available') => {
    draggedItem.value = item
    dragSource.value = source
  }

  const endDrag = () => {
    draggedItem.value = null
    dragSource.value = null
    isDragOver.value = false
  }

  const handleDragOver = (event: DragEvent) => {
    if (dragSource.value === 'available') {
      event.preventDefault()
      isDragOver.value = true
    }
  }

  const handleDragLeave = () => {
    isDragOver.value = false
  }

  const handleDrop = async (event: DragEvent) => {
    event.preventDefault()
    isDragOver.value = false

    if (!draggedItem.value || dragSource.value !== 'available') return

    // Add the dragged item to assigned
    await addSingleItem(draggedItem.value.id)

    draggedItem.value = null
    dragSource.value = null
  }

  // Load data on mount if not provided via props
  onMounted(async () => {
    if (!props.initialAssigned || !props.initialAvailable) {
      isLoading.value = true
      try {
        // Load the parent item to get assigned items
        const parentEndpoint =
          props.parentType === 'product'
            ? `/api/v1/products/${props.parentId}`
            : `/api/v1/projects/${props.parentId}`

        // Load all available items
        const availableEndpoint =
          props.parentType === 'product' ? `/api/v1/projects` : `/api/v1/components`

        const [parentResponse, availableResponse] = await Promise.all([
          $axios.get(parentEndpoint),
          $axios.get(availableEndpoint),
        ])

        // Extract assigned items from parent response
        if (props.parentType === 'product') {
          assignedItems.value = parentResponse.data.projects || []
          // Filter out assigned projects from available list
          const assignedIds = assignedItems.value.map((p: AssignmentItem) => p.id)
          availableItems.value = availableResponse.data.items.filter(
            (p: AssignmentItem) => !assignedIds.includes(p.id)
          )
        } else {
          assignedItems.value = parentResponse.data.components || []
          // Filter out assigned components from available list
          const assignedIds = assignedItems.value.map((c: AssignmentItem) => c.id)
          availableItems.value = availableResponse.data.items.filter(
            (component: AssignmentItem) => {
              const alreadyAssigned = assignedIds.includes(component.id)
              const isGlobalDocument = component.is_global && component.component_type === 'document'
              return !alreadyAssigned && !isGlobalDocument
            }
          )
        }
      } catch (error) {
        console.error('Error loading assignment data:', error)
        showError('Failed to load assignment data')
      } finally {
        isLoading.value = false
      }
    }
  })
</script>

<style scoped>
  .item-assignment-manager {
    position: relative;
  }

  .item-card {
    padding: 1rem;
    border-bottom: 1px solid #dee2e6;
    transition: all 0.2s ease;
    user-select: none;
  }

  .item-card:hover {
    background-color: #f8f9fa;
  }

  .item-card:last-child {
    border-bottom: none;
  }

  .item-card.dragging {
    opacity: 0.5;
    transform: rotate(2deg);
  }

  .drop-zone {
    transition: all 0.2s ease;
  }

  .drop-zone.drag-over {
    background-color: #e8f5e8;
    border: 2px dashed #28a745;
  }

  .loading-overlay {
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background-color: rgba(255, 255, 255, 0.8);
    z-index: 10;
  }

  .assigned-items-container,
  .available-items-container {
    min-height: 200px;
  }

  /* Responsive improvements */
  @media (max-width: 991.98px) {
    .col-lg-6 {
      margin-bottom: 1.5rem;
    }
  }

  @media (max-width: 767.98px) {
    .item-assignment-manager .row {
      margin-left: 0;
      margin-right: 0;
    }

    .item-assignment-manager .row > [class*="col-"] {
      padding-left: 0;
      padding-right: 0;
      margin-bottom: 1.5rem;
    }

    .item-assignment-manager .row > [class*="col-"]:last-child {
      margin-bottom: 0;
    }

    /* Search bar mobile styles - unified single input field */
    .search-container {
      position: sticky !important;
      top: 0 !important;
      z-index: 10 !important;
      background: #ffffff !important;
      margin-bottom: 1rem !important;
      padding: 1rem 0 !important;
      padding-bottom: 1rem !important;
      border-bottom: 1px solid #dee2e6 !important;
    }

    .search-container .input-group {
      display: flex !important;
      flex-wrap: nowrap !important;
      width: 100% !important;
      align-items: stretch !important;
      position: relative !important;
    }

    .search-container .input-group-text {
      position: absolute !important;
      left: 0 !important;
      top: 0 !important;
      bottom: 0 !important;
      z-index: 2 !important;
      background: transparent !important;
      border: none !important;
      border-right: none !important;
      border-radius: 0.375rem 0 0 0.375rem !important;
      padding: 0.5rem 0.75rem !important;
      display: flex !important;
      align-items: center !important;
      justify-content: center !important;
      min-width: 40px !important;
      width: auto !important;
      pointer-events: none !important;
    }

    .search-container .input-group-text i {
      color: #6c757d !important;
      font-size: 0.875rem !important;
      display: block !important;
      line-height: 1 !important;
    }

    .search-container .form-control {
      flex: 1 1 auto !important;
      min-width: 0 !important;
      width: 100% !important;
      border: 1px solid #ced4da !important;
      border-radius: 0.375rem !important;
      padding: 0.5rem 0.75rem 0.5rem 2.75rem !important;
      font-size: 0.875rem !important;
      line-height: 1.5 !important;
      height: auto !important;
      min-height: 38px !important;
      background: #ffffff !important;
      color: #212529 !important;
    }

    .search-container .form-control::placeholder {
      color: #6c757d !important;
      opacity: 1 !important;
    }

    .search-container .form-control:focus {
      border-color: #86b7fe !important;
      box-shadow: 0 0 0 0.25rem rgba(13, 110, 253, 0.25) !important;
      outline: 0 !important;
      z-index: 1 !important;
      background: #ffffff !important;
    }

    /* Ensure card body allows sticky positioning */
    .item-assignment-manager :deep(.card-body) {
      position: relative !important;
      overflow: visible !important;
    }

    .assigned-items-container,
    .available-items-container {
      max-height: 300px;
      min-height: 150px;
    }

    .item-card {
      padding: 0.875rem;
      min-height: 44px;
    }

    .item-header-wrapper {
      flex-direction: column;
      align-items: flex-start !important;
      gap: 0.5rem;
    }

    .item-badges {
      flex-wrap: wrap;
      gap: 0.375rem;
    }
    
    .item-name-wrapper {
      width: 100%;
    }

    .add-item-btn,
    .remove-item-btn {
      width: 36px;
      height: 36px;
      min-width: 36px;
      min-height: 36px;
    }
  }

  @media (max-width: 576px) {
    .item-card {
      padding: 0.75rem;
    }

    .assigned-items-container,
    .available-items-container {
      max-height: 250px;
    }

    .item-badges {
      gap: 0.25rem;
    }
  }

  /* Better scroll styling */
  .assigned-items-container::-webkit-scrollbar,
  .available-items-container::-webkit-scrollbar {
    width: 6px;
  }

  .assigned-items-container::-webkit-scrollbar-track,
  .available-items-container::-webkit-scrollbar-track {
    background: #f1f1f1;
  }

  /* Link styling for item names */
  .item-card a {
    color: #0d6efd !important;
    text-decoration: none !important;
    transition: color 0.2s ease;
  }

  .item-card a:hover {
    color: #0a58ca !important;
    text-decoration: underline !important;
  }

  .item-card a:focus {
    outline: 2px solid #0d6efd;
    outline-offset: 2px;
    border-radius: 2px;
  }

  .assigned-items-container::-webkit-scrollbar-thumb,
  .available-items-container::-webkit-scrollbar-thumb {
    background: #c1c1c1;
    border-radius: 3px;
  }

  .assigned-items-container::-webkit-scrollbar-thumb:hover,
  .available-items-container::-webkit-scrollbar-thumb:hover {
    background: #a8a8a8;
  }

  .add-item-btn,
  .remove-item-btn {
    border-radius: 0.375rem;
    width: 32px;
    height: 32px;
    padding: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: all 0.2s ease;
  }

  .add-item-btn {
    border: 1px solid #0d6efd;
    background: white;
    color: #0d6efd;
  }

  .add-item-btn:hover {
    background: #0d6efd;
    color: white;
    transform: translateY(-1px);
  }

  .remove-item-btn {
    border: 1px solid #dc3545;
    background: white;
    color: #dc3545;
  }

  .remove-item-btn:hover {
    background: #dc3545;
    color: white;
    transform: translateY(-1px);
  }

  .add-item-btn:disabled,
  .remove-item-btn:disabled {
    opacity: 0.6;
    cursor: not-allowed;
    transform: none;
  }

  .version-display {
    display: inline-block;
    max-width: 100px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    vertical-align: bottom;
  }
</style>
