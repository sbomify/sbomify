/**
 * Configuration constants used throughout the application
 */

export const RELEASE_DISPLAY = {
  /** Maximum number of releases to show before requiring expansion */
  MAX_INITIAL_DISPLAY: 3,
  /** Maximum number of releases to show when expanded (prevents UI overflow) */
  MAX_EXPANDED_DISPLAY: 10,
  /** Threshold for showing "View all" link instead of expansion */
  VIEW_ALL_THRESHOLD: 10
} as const

export const PAGINATION = {
  /** Default page size for tables */
  DEFAULT_PAGE_SIZE: 15
} as const

export const MODAL_Z_INDEX = {
  /** Base z-index for modals */
  MODAL: 1055,
  /** Z-index for modal backdrops */
  BACKDROP: 1050
} as const

export const EXPANSION_LIMITS = {
  /** For releases: show first N without expansion */
  INITIAL_RELEASES: 3,
  /** For releases: show additional N when expanded (for medium lists) */
  EXPANDED_RELEASES: 7
} as const