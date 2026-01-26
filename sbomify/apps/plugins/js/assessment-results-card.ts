/**
 * Assessment Results Card
 *
 * This component has been simplified to use server-side rendering with Django templates.
 * Bootstrap's collapse component handles the expand/collapse functionality.
 *
 * The only JavaScript needed is for handling URL hash navigation to specific plugins
 * and toggling package lists in findings.
 */

import Alpine from 'alpinejs';
import { scrollTo } from '../../core/js/components/scroll-to';

// Extend Window interface for togglePackages global function
declare global {
  interface Window {
    togglePackages: typeof togglePackages
  }
}

/**
 * Alpine component for assessment results card
 * Handles hash navigation and package toggling
 */
export function registerAssessmentResultsCard(): void {
  // Register global toggle function for package lists (called from inline onclick handlers)
  registerPackageToggle();

  // Alpine component for hash navigation
  Alpine.data('assessmentResultsCard', () => {
    return {
      init() {
        // Handle anchor links on page load
        this.handleAnchorLink();
      },
      
      handleAnchorLink() {
        const hash = window.location.hash;

        if (!hash) return;

        if (hash.startsWith('#plugin-')) {
          const pluginName = hash.replace('#plugin-', '');
          const element = document.getElementById(`plugin-${pluginName}`);

          if (element) {
            // Find the collapse element within this accordion item
            const collapseEl = element.querySelector('.accordion-collapse');
            if (collapseEl) {
              // Use Alpine x-collapse - find the parent with x-data and set isExpanded = true
              const accordionItem = collapseEl.closest('.accordion-item');
              if (accordionItem) {
                const accordionData = Alpine.$data(accordionItem as HTMLElement) as { isExpanded?: boolean } | null;
                if (accordionData && typeof accordionData.isExpanded === 'boolean') {
                  accordionData.isExpanded = true;
                } else {
                  // Fallback: directly show the collapse element
                  collapseEl.classList.add('show');
                  collapseEl.setAttribute('x-show', 'true');
                }
              }
            }

            // Scroll to the element
            scrollTo(element, { behavior: 'smooth', block: 'start' });
          }
        } else if (hash === '#assessment-results') {
          const element = document.getElementById('assessment-results');
          if (element) {
            scrollTo(element, { behavior: 'smooth', block: 'start' });
          }
        }
      }
    };
  });
}

// Legacy function for backwards compatibility
export function initAssessmentResultsCard(): void {
  // No longer needed - handled by Alpine component
  // Keep for backwards compatibility
  registerPackageToggle();
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

