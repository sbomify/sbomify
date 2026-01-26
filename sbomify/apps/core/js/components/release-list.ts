import Alpine from 'alpinejs'

const MAX_INITIAL_DISPLAY = 3
const MAX_EXPANDED_DISPLAY = 10

interface Release {
  id: string
  version: string
  product_id: string
  product_name: string
  name: string
  is_latest: boolean
  is_prerelease: boolean
}

export function registerReleaseList(): void {
  Alpine.data('releaseList', (itemId: string, releasesJson: string) => {
    const releases: Release[] = JSON.parse(releasesJson)

    return {
      releases: releases || [],
      itemId,
      // Use $persist with sessionStorage for expansion state
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      isExpanded: (Alpine as any).$persist(false)
        .as(`release-expanded-${itemId}`)
        .using(sessionStorage),

      get displayedReleases(): Release[] {
        if (this.releases.length <= MAX_INITIAL_DISPLAY) {
          return this.releases
        }

        const maxDisplay = this.isExpanded ? MAX_EXPANDED_DISPLAY : MAX_INITIAL_DISPLAY
        return this.releases.slice(0, maxDisplay)
      },

      get shouldShowExpansion(): boolean {
        return this.releases.length > MAX_INITIAL_DISPLAY
      },

      get remainingCount(): number {
        const maxDisplay = this.isExpanded ? MAX_EXPANDED_DISPLAY : MAX_INITIAL_DISPLAY
        return Math.max(0, this.releases.length - maxDisplay)
      },

      get expandButtonText(): string {
        if (this.isExpanded) {
          return '− Show less'
        }
        return `+ ${this.remainingCount} more`
      },

      toggleExpansion(): void {
        this.isExpanded = !this.isExpanded
        // No manual sessionStorage needed - $persist handles it automatically
      }
    }
  })
}
