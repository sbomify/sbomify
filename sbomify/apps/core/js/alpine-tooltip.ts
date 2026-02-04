/**
 * Alpine.js Tooltip Directive
 * Replaces Bootstrap tooltips with a lightweight Alpine.js alternative
 *
 * Usage (with x-data context for reactive expressions):
 * <div x-data="{ msg: 'Hello' }">
 *   <button x-tooltip="msg">Hover me</button>
 * </div>
 *
 * Usage (standalone with string literals - no x-data required):
 * <button x-tooltip="'Tooltip text'">Hover me</button>
 * <button x-tooltip.top="'Top tooltip'">Hover me</button>
 * <button x-tooltip.bottom="'Bottom tooltip'">Hover me</button>
 * <button x-tooltip.left="'Left tooltip'">Hover me</button>
 * <button x-tooltip.right="'Right tooltip'">Hover me</button>
 */

import type { Alpine as AlpineType } from 'alpinejs';

/** Alpine.js directive binding parameters */
interface DirectiveBinding {
  expression: string;
  modifiers: string[];
}

/** Alpine.js directive utilities */
interface DirectiveUtilities {
  evaluate: <T>(expression: string) => T;
  cleanup: (callback: () => void) => void;
}

type TooltipPlacement = 'top' | 'bottom' | 'left' | 'right';

/**
 * Safely evaluate tooltip text with fallback to literal string
 * This allows the directive to work both with and without x-data context
 * @internal Exported for testing
 */
export function getTooltipText(expression: string, evaluate: <T>(expr: string) => T): string {
  if (!expression) return '';

  // Try to evaluate as an Alpine expression first
  try {
    const result = evaluate<string>(expression);
    if (result) return result;
  } catch {
    // Evaluation failed, likely no x-data context
  }

  // Check if it looks like a string literal (starts and ends with quotes)
  const trimmed = expression.trim();
  if ((trimmed.startsWith("'") && trimmed.endsWith("'")) ||
      (trimmed.startsWith('"') && trimmed.endsWith('"'))) {
    // Remove the quotes and return the inner string
    return trimmed.slice(1, -1);
  }

  // Fall back to treating the entire expression as plain text
  return expression;
}

export function registerTooltipDirective(Alpine: AlpineType) {
  Alpine.directive('tooltip', (el: HTMLElement, { expression, modifiers }: DirectiveBinding, { evaluate, cleanup }: DirectiveUtilities) => {
    const tooltipText = getTooltipText(expression, evaluate);
    if (!tooltipText) return;

    // Determine placement from modifiers
    const placement: TooltipPlacement = modifiers.includes('bottom') ? 'bottom' :
                     modifiers.includes('left') ? 'left' :
                     modifiers.includes('right') ? 'right' :
                     'top'; // default

    let tooltipEl: HTMLElement | null = null;
    let showTimeout: ReturnType<typeof setTimeout> | null = null;
    let hideTimeout: ReturnType<typeof setTimeout> | null = null;

    const createTooltip = () => {
      tooltipEl = document.createElement('div');
      tooltipEl.className = 'alpine-tooltip';
      tooltipEl.textContent = tooltipText;
      tooltipEl.setAttribute('role', 'tooltip');
      document.body.appendChild(tooltipEl);
    };

    const positionTooltip = () => {
      if (!tooltipEl) return;

      const rect = el.getBoundingClientRect();
      const tooltipRect = tooltipEl.getBoundingClientRect();
      const offset = 8; // Distance from element

      let top = 0;
      let left = 0;

      switch (placement) {
        case 'top':
          top = rect.top - tooltipRect.height - offset;
          left = rect.left + (rect.width - tooltipRect.width) / 2;
          break;
        case 'bottom':
          top = rect.bottom + offset;
          left = rect.left + (rect.width - tooltipRect.width) / 2;
          break;
        case 'left':
          top = rect.top + (rect.height - tooltipRect.height) / 2;
          left = rect.left - tooltipRect.width - offset;
          break;
        case 'right':
          top = rect.top + (rect.height - tooltipRect.height) / 2;
          left = rect.right + offset;
          break;
      }

      // Keep tooltip within viewport
      const padding = 4;
      top = Math.max(padding, Math.min(top, window.innerHeight - tooltipRect.height - padding));
      left = Math.max(padding, Math.min(left, window.innerWidth - tooltipRect.width - padding));

      tooltipEl.style.top = `${top + window.scrollY}px`;
      tooltipEl.style.left = `${left + window.scrollX}px`;
      tooltipEl.setAttribute('data-placement', placement);
    };

    const showTooltip = () => {
      if (hideTimeout) {
        clearTimeout(hideTimeout);
        hideTimeout = null;
      }

      showTimeout = setTimeout(() => {
        if (!tooltipEl) {
          createTooltip();
        }
        if (tooltipEl) {
          positionTooltip();
          tooltipEl.classList.add('show');
        }
      }, 200); // Slight delay before showing
    };

    const hideTooltip = () => {
      if (showTimeout) {
        clearTimeout(showTimeout);
        showTimeout = null;
      }

      hideTimeout = setTimeout(() => {
        if (tooltipEl) {
          tooltipEl.classList.remove('show');
          setTimeout(() => {
            if (tooltipEl && !tooltipEl.classList.contains('show')) {
              tooltipEl.remove();
              tooltipEl = null;
            }
          }, 150); // Wait for fade out animation
        }
      }, 100);
    };

    // Event listeners
    el.addEventListener('mouseenter', showTooltip);
    el.addEventListener('mouseleave', hideTooltip);
    el.addEventListener('focus', showTooltip);
    el.addEventListener('blur', hideTooltip);

    // Register cleanup via Alpine.js directive utilities
    cleanup(() => {
      if (showTimeout) clearTimeout(showTimeout);
      if (hideTimeout) clearTimeout(hideTimeout);
      if (tooltipEl) {
        tooltipEl.remove();
        tooltipEl = null;
      }
      el.removeEventListener('mouseenter', showTooltip);
      el.removeEventListener('mouseleave', hideTooltip);
      el.removeEventListener('focus', showTooltip);
      el.removeEventListener('blur', hideTooltip);
    });
  });
}
