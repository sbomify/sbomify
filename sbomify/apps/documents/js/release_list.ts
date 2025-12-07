import Alpine from 'alpinejs'

interface Release {
  id: string
  version: string
  [key: string]: unknown
}

interface ReleaseListData {
  releases: Release[]
  itemId: string
  isPublicView: boolean
}

export function registerReleaseList() {
  Alpine.data('releaseList', (releasesJson: string, itemId: string, isPublicView: boolean) => {
    const releases = JSON.parse(releasesJson)
    const data: ReleaseListData = {
      releases,
      itemId,
      isPublicView
    }
    const MAX_INITIAL_DISPLAY = 3
    const MAX_EXPANDED_DISPLAY = 10

    const getInitialExpandedState = (): boolean => {
      return sessionStorage.getItem(`release-expanded-${data.itemId}`) === 'true'
    }

    return {
      releases: data.releases || [],
      itemId: data.itemId,
      isPublicView: data.isPublicView || false,
      isExpanded: getInitialExpandedState(),

      get displayedReleases() {
        if (this.releases.length <= MAX_INITIAL_DISPLAY) {
          return this.releases
        }

        if (this.isExpanded) {
          return this.releases.slice(0, Math.min(MAX_EXPANDED_DISPLAY, this.releases.length))
        }

        return this.releases.slice(0, MAX_INITIAL_DISPLAY)
      },

      get shouldShowExpansion(): boolean {
        return this.releases.length > MAX_INITIAL_DISPLAY
      },

      get remainingCount(): number {
        if (this.isExpanded) {
          return Math.max(0, this.releases.length - MAX_EXPANDED_DISPLAY)
        }
        return Math.max(0, this.releases.length - MAX_INITIAL_DISPLAY)
      },

      toggleExpansion(): void {
        this.isExpanded = !this.isExpanded
        sessionStorage.setItem(`release-expanded-${this.itemId}`, this.isExpanded.toString())
      },

      getExpandButtonText(): string {
        if (this.isExpanded) {
          return '− Show less'
        }
        return `+ ${this.remainingCount} more`
      }
    }
  })
}
