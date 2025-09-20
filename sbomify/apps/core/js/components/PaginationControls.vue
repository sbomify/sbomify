<template>
  <div v-if="totalPages > 1" class="pagination-controls">
    <div class="d-flex justify-content-between align-items-center">
      <!-- Page info and items per page selector -->
      <div class="d-flex align-items-center gap-3">
        <small class="text-muted">
          Showing {{ startItem }}-{{ endItem }} of {{ totalItems }} items
        </small>

        <div v-if="showPageSizeSelector" class="d-flex align-items-center gap-2">
          <label class="small text-muted mb-0">Items per page:</label>
          <select
            :value="pageSize"
            class="form-select form-select-sm"
            style="width: auto;"
            @change="handlePageSizeChange"
          >
            <option v-for="size in pageSizeOptions" :key="size" :value="size">
              {{ size }}
            </option>
          </select>
        </div>
      </div>

      <!-- Pagination navigation -->
      <nav v-if="totalPages > 1">
        <ul class="pagination pagination-sm mb-0">
          <li class="page-item" :class="{ disabled: currentPage === 1 }">
            <button
              class="page-link"
              :disabled="currentPage === 1"
              title="First page"
              @click="goToPage(1)"
            >
              First
            </button>
          </li>
          <li class="page-item" :class="{ disabled: currentPage === 1 }">
            <button
              class="page-link"
              :disabled="currentPage === 1"
              title="Previous page"
              @click="goToPage(currentPage - 1)"
            >
              Previous
            </button>
          </li>

          <!-- Page numbers (show ellipsis for large page counts) -->
          <template v-for="page in visiblePages" :key="page">
            <li v-if="page === '...'" class="page-item disabled">
              <span class="page-link">...</span>
            </li>
            <li v-else class="page-item" :class="{ active: page === currentPage }">
              <button
                class="page-link"
                :title="`Go to page ${page}`"
                @click="typeof page === 'number' ? goToPage(page) : undefined"
              >
                {{ page }}
              </button>
            </li>
          </template>

          <li class="page-item" :class="{ disabled: currentPage === totalPages }">
            <button
              class="page-link"
              :disabled="currentPage === totalPages"
              title="Next page"
              @click="goToPage(currentPage + 1)"
            >
              Next
            </button>
          </li>
          <li class="page-item" :class="{ disabled: currentPage === totalPages }">
            <button
              class="page-link"
              :disabled="currentPage === totalPages"
              title="Last page"
              @click="goToPage(totalPages)"
            >
              Last
            </button>
          </li>
        </ul>
      </nav>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

interface Props {
  currentPage: number
  totalPages: number
  totalItems: number
  pageSize: number
  showPageSizeSelector?: boolean
  pageSizeOptions?: number[]
}

interface Emits {
  (e: 'update:currentPage', value: number): void
  (e: 'update:pageSize', value: number): void
}

const props = withDefaults(defineProps<Props>(), {
  showPageSizeSelector: true,
  pageSizeOptions: () => [10, 15, 25, 50, 100]
})

const emit = defineEmits<Emits>()

// Computed properties
const startItem = computed(() => {
  return props.totalItems === 0 ? 0 : (props.currentPage - 1) * props.pageSize + 1
})

const endItem = computed(() => {
  return Math.min(props.currentPage * props.pageSize, props.totalItems)
})

const visiblePages = computed(() => {
  const pages: (number | string)[] = []
  const maxVisiblePages = 7

  if (props.totalPages <= maxVisiblePages) {
    // Show all pages if total is small
    for (let i = 1; i <= props.totalPages; i++) {
      pages.push(i)
    }
  } else {
    // Show pages with ellipsis for large page counts
    const start = Math.max(1, props.currentPage - 2)
    const end = Math.min(props.totalPages, props.currentPage + 2)

    if (start > 1) {
      pages.push(1)
      if (start > 2) {
        pages.push('...')
      }
    }

    for (let i = start; i <= end; i++) {
      pages.push(i)
    }

    if (end < props.totalPages) {
      if (end < props.totalPages - 1) {
        pages.push('...')
      }
      pages.push(props.totalPages)
    }
  }

  return pages
})

// Event handlers
const goToPage = (page: number) => {
  if (page >= 1 && page <= props.totalPages && page !== props.currentPage) {
    emit('update:currentPage', page)
  }
}

const handlePageSizeChange = (event: Event) => {
  const target = event.target as HTMLSelectElement
  const newPageSize = parseInt(target.value, 10)
  emit('update:pageSize', newPageSize)
}
</script>

<style scoped>
.pagination-controls {
  margin-top: 1rem;
  padding-top: 1rem;
  border-top: 1px solid #e9ecef;
}

.page-link {
  border: none;
  background: none;
  color: #6c757d;
  padding: 0.375rem 0.75rem;
  transition: all 0.15s ease-in-out;
}

.page-link:hover:not(:disabled) {
  background-color: #e9ecef;
  color: #495057;
}

.page-item.active .page-link {
  background-color: #007bff;
  color: white;
}

.page-item.disabled .page-link {
  color: #6c757d;
  cursor: not-allowed;
}

.form-select-sm {
  min-width: 60px;
}
</style>