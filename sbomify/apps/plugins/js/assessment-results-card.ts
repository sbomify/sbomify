/**
 * Assessment Results Card
 *
 * This component uses server-side rendering with Django templates.
 * Alpine opens one assessment report at a time from the scorecard tiles.
 *
 * The only JavaScript needed is for handling URL hash navigation to specific plugins
 * and toggling package lists in findings.
 */

// Extend Window interface for togglePackages global function
declare global {
  interface Window {
    togglePackages: typeof togglePackages
  }
}

export function initAssessmentResultsCard(): void {
  // Handle anchor links on page load
  handleAnchorLink()

  // Listen for hash changes
  window.addEventListener('hashchange', handleAnchorLink)

  // Register global toggle function for package lists
  registerPackageToggle()
}

/**
 * Toggle visibility of hidden packages in finding descriptions.
 *
 * This function is exposed globally on {@link window} and is invoked from
 * inline `onclick` handlers in template-rendered HTML (see plugins_extras.py
 * format_finding_description filter).
 *
 * @param button - The toggle button element that was clicked. This should be
 *   the button inside a `.missing-packages` container whose visibility state
 *   will be toggled.
 */
function togglePackages(button: HTMLButtonElement): void {
  const container = button.closest('.missing-packages')
  if (!container) return

  const isExpanded = button.dataset.expanded === 'true'
  const moreSpan = button.querySelector('.pkg-toggle-more') as HTMLElement
  const lessSpan = button.querySelector('.pkg-toggle-less') as HTMLElement

  if (isExpanded) {
    // Collapse
    container.classList.remove('expanded')
    button.dataset.expanded = 'false'
    if (moreSpan) moreSpan.style.display = ''
    if (lessSpan) lessSpan.style.display = 'none'
  } else {
    // Expand
    container.classList.add('expanded')
    button.dataset.expanded = 'true'
    if (moreSpan) moreSpan.style.display = 'none'
    if (lessSpan) lessSpan.style.display = ''
  }
}

/**
 * Register the toggle function globally so it can be called from onclick handlers.
 */
function registerPackageToggle(): void {
  // Make togglePackages available globally for onclick handlers
  window.togglePackages = togglePackages
}

function handleAnchorLink(): void {
  const hash = window.location.hash

  if (!hash) return

  if (hash.startsWith('#plugin-')) {
    const pluginName = hash.replace('#plugin-', '')
    const element = document.getElementById(`plugin-${pluginName}`)

    if (element) {
      // Open the tile's report. The click also fetches its findings, but only
      // once htmx has wired the listener, which may not have happened yet.
      const engine = (window as Window & { htmx?: { process(el: Element): void } }).htmx
      engine?.process(element.closest('#assessment-results') ?? element)
      const trigger = element.querySelector<HTMLButtonElement>('button[aria-expanded="false"]')
      trigger?.click()

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
