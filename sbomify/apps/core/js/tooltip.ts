import Alpine from './alpine-init';

type BootstrapTooltip = {
    dispose: () => void;
};

/**
 * Alpine.js directive for managing Bootstrap tooltips with proper lifecycle
 * Usage: <button x-tooltip="'Tooltip text'">Button</button>
 * Or: <button x-tooltip.html="'<b>Bold</b> tooltip'">Button</button>
 */
export function registerTooltipDirective() {
    Alpine.directive('tooltip', (el, { expression, modifiers }, { evaluateLater, cleanup }) => {
        const getContent = evaluateLater(expression);
        let tooltip: BootstrapTooltip | null = null;

        const initTooltip = () => {
            getContent((value: unknown) => {
                const content = String(value);
                if (!content) return;

                // Dispose existing tooltip if any
                if (tooltip) {
                    tooltip.dispose();
                }

                // Initialize new tooltip
                if (window.bootstrap) {
                    tooltip = new window.bootstrap.Tooltip(el, {
                        title: content,
                        html: modifiers.includes('html'),
                        delay: { show: 300, hide: 100 },
                        animation: true,
                        trigger: 'hover focus',
                        placement: modifiers.includes('top') ? 'top' :
                                  modifiers.includes('bottom') ? 'bottom' :
                                  modifiers.includes('left') ? 'left' :
                                  modifiers.includes('right') ? 'right' : 'top'
                    });
                }
            });
        };

        initTooltip();

        // Cleanup when element is removed
        cleanup(() => {
            if (tooltip) {
                tooltip.dispose();
                tooltip = null;
            }
        });
    });
}

/**
 * Alpine.js component for managing tooltips in a container
 * Automatically initializes and cleans up tooltips for elements with data-bs-toggle="tooltip"
 */
export function registerTooltipManager() {
    Alpine.data('tooltipManager', () => ({
        tooltips: [] as BootstrapTooltip[],

        init() {
            this.$nextTick(() => {
                this.initializeTooltips();
            });
        },

        initializeTooltips() {
            // Dispose existing tooltips
            this.disposeTooltips();

            // Initialize new tooltips
            const tooltipElements = this.$el.querySelectorAll('[data-bs-toggle="tooltip"]');
            this.tooltips = Array.from(tooltipElements).map((el: Element) => {
                if (window.bootstrap) {
                    return new window.bootstrap.Tooltip(el, {
                        delay: { show: 300, hide: 100 },
                        animation: true,
                        trigger: 'hover focus'
                    }) as BootstrapTooltip;
                }
                return null;
            }).filter((tooltip): tooltip is BootstrapTooltip => tooltip !== null);
        },

        disposeTooltips() {
            this.tooltips.forEach(tooltip => {
                if (tooltip) {
                    tooltip.dispose();
                }
            });
            this.tooltips = [];
        },

        destroy() {
            this.disposeTooltips();
        }
    }));
}

/**
 * Global tooltip cleanup utility for HTMX swaps
 * Call this during HTMX:beforeSwap to prevent orphaned tooltips
 */
export function cleanupOrphanedTooltips(container?: Element) {
    const targetContainer = container || document.body;

    // Dispose all tooltip instances in the container
    const tooltipElements = targetContainer.querySelectorAll('[data-bs-toggle="tooltip"]');
    tooltipElements.forEach((el) => {
        const instance = window.bootstrap?.Tooltip?.getInstance(el);
        if (instance) {
            instance.dispose();
        }
    });

    // Remove any visible tooltip elements that are orphaned
    document.querySelectorAll('.tooltip.show').forEach((tooltipEl) => {
        const id = tooltipEl.getAttribute('id');
        if (id) {
            // Check if the trigger element exists
            const trigger = document.querySelector(`[aria-describedby="${id}"]`);
            if (!trigger || (container && !container.contains(trigger))) {
                tooltipEl.remove();
            }
        }
    });
}
