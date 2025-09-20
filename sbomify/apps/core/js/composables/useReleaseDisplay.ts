import { ref, computed } from 'vue'
import { RELEASE_DISPLAY, EXPANSION_LIMITS } from '../constants'

export interface Release {
  id: string
  name: string
  product_name: string
  is_latest: boolean
  is_prerelease: boolean
  is_public: boolean
  product_id?: string
  product?: {
    id: string
    name: string
  }
}

/**
 * Composable for handling release display logic including expansion,
 * URL generation, and filtering
 */
export function useReleaseDisplay(isPublicView = false) {
  // State for expansion tracking
  const expandedReleases = ref<Set<string>>(new Set())

  /**
   * Get releases to display based on expansion state
   */
  const getDisplayReleases = (releases: Release[], expansionKey: string): Release[] => {
    if (releases.length <= RELEASE_DISPLAY.MAX_INITIAL_DISPLAY) {
      return releases
    }

    if (expandedReleases.value.has(expansionKey)) {
      // When expanded, show max releases to avoid overwhelming the UI
      return releases.slice(0, Math.min(RELEASE_DISPLAY.MAX_EXPANDED_DISPLAY, releases.length))
    }

    return releases.slice(0, RELEASE_DISPLAY.MAX_INITIAL_DISPLAY)
  }

  /**
   * Toggle expansion state for a specific item
   */
  const toggleReleaseExpansion = (expansionKey: string): void => {
    if (expandedReleases.value.has(expansionKey)) {
      expandedReleases.value.delete(expansionKey)
    } else {
      expandedReleases.value.add(expansionKey)
    }
  }

  /**
   * Check if releases are expanded for a specific item
   */
  const isReleaseExpanded = (expansionKey: string): boolean => {
    return expandedReleases.value.has(expansionKey)
  }

  /**
   * Generate URL for a specific release
   */
  const getReleaseUrl = (release: Release): string => {
    const productId = release.product_id || release.product?.id
    if (productId) {
      if (isPublicView) {
        return `/public/product/${productId}/release/${release.id}/`
      }
      return `/product/${productId}/release/${release.id}/`
    }
    return '#'
  }

  /**
   * Get latest releases from a list
   */
  const getLatestReleases = (releases: Release[]): Release[] => {
    const productMap = new Map<string, Release>()

    releases.forEach(release => {
      if (release.is_latest) {
        productMap.set(release.product_id || release.product?.id || 'unknown', release)
      }
    })

    return Array.from(productMap.values())
  }

  /**
   * Get count of latest releases
   */
  const getLatestReleasesCount = (releases: Release[]): number => {
    return getLatestReleases(releases).length
  }

  /**
   * Get badge text for latest releases
   */
  const getLatestBadgeText = (releases: Release[]): string => {
    const latestCount = getLatestReleasesCount(releases)
    if (latestCount <= 1) {
      return 'Latest'
    }
    return `Latest in ${latestCount} products`
  }

  /**
   * Generate tooltip text for releases
   */
  const getReleasesTooltip = (releases: Release[]): string => {
    const products = [...new Set(releases.map(r => r.product_name || r.product?.name))].join(', ')
    return `${products} - ${releases.length} release${releases.length === 1 ? '' : 's'}`
  }

  /**
   * Generate expansion key for a list of releases (using the item ID)
   */
  const getExpansionKey = (itemId: string): string => {
    return itemId
  }

  /**
   * Check if expansion controls should be shown
   */
  const shouldShowExpansion = (releases: Release[]): boolean => {
    return releases.length > RELEASE_DISPLAY.MAX_INITIAL_DISPLAY
  }

  /**
   * Check if "View all" link should be shown instead of expansion
   */
  const shouldShowViewAll = (releases: Release[]): boolean => {
    return releases.length > RELEASE_DISPLAY.VIEW_ALL_THRESHOLD
  }

  /**
   * Get remaining count for expansion button
   */
  const getRemainingCount = (releases: Release[], expansionKey: string): number => {
    if (isReleaseExpanded(expansionKey)) {
      return Math.max(0, releases.length - RELEASE_DISPLAY.MAX_EXPANDED_DISPLAY)
    }
    return Math.max(0, releases.length - RELEASE_DISPLAY.MAX_INITIAL_DISPLAY)
  }

  /**
   * Get text for expansion button
   */
  const getExpansionButtonText = (releases: Release[], expansionKey: string): string => {
    if (isReleaseExpanded(expansionKey)) {
      return '− Show less'
    }
    const remaining = getRemainingCount(releases, expansionKey)
    if (shouldShowViewAll(releases)) {
      return `+ ${Math.min(EXPANSION_LIMITS.EXPANDED_RELEASES, remaining)} more`
    }
    return `+ ${remaining} more`
  }

  return {
    // State
    expandedReleases: computed(() => expandedReleases.value),

    // Actions
    getDisplayReleases,
    toggleReleaseExpansion,
    isReleaseExpanded,
    getReleaseUrl,
    getLatestReleases,
    getLatestReleasesCount,
    getLatestBadgeText,
    getReleasesTooltip,
    getExpansionKey,
    shouldShowExpansion,
    shouldShowViewAll,
    getRemainingCount,
    getExpansionButtonText
  }
}