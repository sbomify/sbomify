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

    get totalPages(): number {
      return Math.ceil(this.totalItems / this.pageSize) || 1
    },

    get startItem(): number {
      return this.totalItems === 0 ? 0 : (this.currentPage - 1) * this.pageSize + 1
    },

    get endItem(): number {
      return Math.min(this.currentPage * this.pageSize, this.totalItems)
    },

    get visiblePages(): (number | string)[] {
      const pages: (number | string)[] = []
      const maxVisiblePages = 7

      if (this.totalPages <= maxVisiblePages) {
        for (let i = 1; i <= this.totalPages; i++) {
          pages.push(i)
        }
      } else {
        const start = Math.max(1, this.currentPage - 2)
        const end = Math.min(this.totalPages, this.currentPage + 2)

        if (start > 1) {
          pages.push(1)
          if (start > 2) {
            pages.push('...')
          }
        }

        for (let i = start; i <= end; i++) {
          pages.push(i)
        }

        if (end < this.totalPages) {
          if (end < this.totalPages - 1) {
            pages.push('...')
          }
          pages.push(this.totalPages)
        }
      }

      return pages
    },

    goToPage(page: number): void {
      if (page < 1 || page > this.totalPages || page === this.currentPage) {
        return;
      }
      this.currentPage = page
    },

    handlePageSizeChange(event: Event): void {
      this.pageSize = parseInt((event.target as HTMLSelectElement).value, 10)
      this.currentPage = 1
    }
  }
}
