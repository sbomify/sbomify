/**
 * Assessment Results Card
 *
 * This component has been simplified to use server-side rendering with Django templates.
 * Bootstrap's collapse component handles the expand/collapse functionality.
 *
 * The only JavaScript needed is for handling URL hash navigation to specific plugins.
 */

import { Collapse } from 'bootstrap'

export function initAssessmentResultsCard(): void {
  // Handle anchor links on page load
  handleAnchorLink()

  // Listen for hash changes
  window.addEventListener('hashchange', handleAnchorLink)
}

function handleAnchorLink(): void {
  const hash = window.location.hash

  if (!hash) return

  if (hash.startsWith('#plugin-')) {
    const pluginName = hash.replace('#plugin-', '')
    const element = document.getElementById(`plugin-${pluginName}`)

    if (element) {
      // Find the collapse element within this accordion item
      const collapseEl = element.querySelector('.accordion-collapse')
      if (collapseEl) {
        // Use Bootstrap's Collapse API to show it
        const bsCollapse = new Collapse(collapseEl)
        bsCollapse.show()
      }

      // Scroll to the element
      setTimeout(() => {
        element.scrollIntoView({ behavior: 'smooth', block: 'start' })
      }, 100)
    }
  } else if (hash === '#assessment-results') {
    const element = document.getElementById('assessment-results')
    if (element) {
      element.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  }
}

// For backwards compatibility, keep the Alpine registration but make it a no-op
export function registerAssessmentResultsCard(): void {
  // No longer needed - using server-side rendering
  // Keep function for backwards compatibility with main.ts imports
}
