const MAX_VISIBLE_PAGES = 7
const PAGES_AROUND_CURRENT = 2
const ELLIPSIS = '...'

export function createPaginationData(
  totalItems: number,
  pageSizeOptions: number[] = [10, 15, 25, 50, 100],
  initialPage: number = 1
) {
  return {
    currentPage: initialPage,
    totalItems,
    pageSize: pageSizeOptions[0],
    pageSizeOptions,
    ellipsis: ELLIPSIS,

    get totalPages(): number {
      return Math.ceil(this.totalItems / this.pageSize) || 1
    },

    get startItem(): number {
      return this.totalItems === 0 ? 0 : (this.currentPage - 1) * this.pageSize + 1
    },

    get endItem(): number {
      return Math.min(this.currentPage * this.pageSize, this.totalItems)
    },

    isVisible(index: number): boolean {
      const start = (this.currentPage - 1) * this.pageSize
      const end = start + this.pageSize
      return index >= start && index < end
    },

    get visiblePages(): (number | string)[] {
      const pages: (number | string)[] = []

      if (this.totalPages <= MAX_VISIBLE_PAGES) {
        for (let i = 1; i <= this.totalPages; i++) {
          pages.push(i)
        }
        return pages
      }

      const startPage = Math.max(1, this.currentPage - PAGES_AROUND_CURRENT)
      const endPage = Math.min(this.totalPages, this.currentPage + PAGES_AROUND_CURRENT)

      if (startPage > 1) {
        pages.push(1)
        if (startPage > 2) {
          pages.push(ELLIPSIS)
        }
      }

      for (let i = startPage; i <= endPage; i++) {
        pages.push(i)
      }

      if (endPage < this.totalPages) {
        if (endPage < this.totalPages - 1) {
          pages.push(ELLIPSIS)
        }
        pages.push(this.totalPages)
      }

      return pages
    },

    goToPage(page: number): void {
      if (page < 1 || page > this.totalPages || page === this.currentPage) {
        return
      }
      this.currentPage = page
    },

    handlePageSizeChange(event: Event): void {
      this.pageSize = parseInt((event.target as HTMLSelectElement).value, 10)
      this.currentPage = 1
    }
  }
}
