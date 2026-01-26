import Alpine from 'alpinejs';

/**
 * Pure Alpine.js tooltip directive
 * 
 * Replaces Bootstrap JS tooltips with Alpine.js state management
 * Still uses Bootstrap CSS classes for styling consistency
 * 
 * Usage:
 *   <button x-tooltip="'Tooltip text'">Button</button>
 *   <button x-tooltip.top="'Tooltip text'">Button</button>
 *   <button x-tooltip.html="'<b>Bold</b> text'">Button</button>
 *   <button data-bs-toggle="tooltip" title="Tooltip text">Button</button> (auto-converted)
 * 
 * Modifiers:
 *   .top, .bottom, .left, .right - Positioning (default: top)
 *   .html - Allow HTML content
 */
export function registerAlpineTooltip(): void {
    /**
     * Main x-tooltip directive
     * Creates tooltip using Alpine state and Bootstrap CSS
     */
    Alpine.directive('tooltip', (el, { expression, modifiers }, { evaluateLater, cleanup }) => {
        if (!(el instanceof HTMLElement)) return;

        const allowHtml = modifiers.includes('html');
        const placement = (modifiers.find(m => ['top', 'bottom', 'left', 'right'].includes(m)) || 'top') as 'top' | 'bottom' | 'left' | 'right';

        let tooltipElement: HTMLElement | null = null;
        let tooltipId: string | null = null;
        let getContent: ((callback: (value: unknown) => void) => void) | null = null;
        let showTooltip = false;

        // Get content from expression, title attribute, or data-bs-original-title
        if (expression) {
            getContent = evaluateLater(expression);
        } else if (el.title) {
            const titleContent = el.title;
            el.removeAttribute('title');
            getContent = (callback: (value: unknown) => void) => callback(titleContent);
        } else if (el.getAttribute('data-bs-original-title')) {
            const titleContent = el.getAttribute('data-bs-original-title') || '';
            el.removeAttribute('data-bs-original-title');
            getContent = (callback: (value: unknown) => void) => callback(titleContent);
        } else {
            return; // No content available
        }

        // Create tooltip element
        const createTooltip = () => {
            if (!getContent) return;

            getContent((value: unknown) => {
                const content = String(value || '');
                if (!content) return;

                // Remove existing tooltip if any
                if (tooltipElement) {
                    tooltipElement.remove();
                }

                // Create tooltip element using Bootstrap CSS classes
                tooltipElement = document.createElement('div');
                tooltipId = `alpine-tooltip-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
                tooltipElement.id = tooltipId;
                tooltipElement.className = `tooltip bs-tooltip-${placement} fade`;
                tooltipElement.setAttribute('role', 'tooltip');
                // Don't use x-show here - tooltip is not in Alpine context
                // We'll use direct DOM manipulation instead
                tooltipElement.style.position = 'absolute';
                tooltipElement.style.zIndex = '9999';
                tooltipElement.style.pointerEvents = 'none';
                tooltipElement.style.display = 'none';

                // Create inner tooltip arrow and content
                const arrow = document.createElement('div');
                arrow.className = 'tooltip-arrow';

                const inner = document.createElement('div');
                inner.className = 'tooltip-inner';

                if (allowHtml) {
                    inner.innerHTML = content;
                } else {
                    inner.textContent = content;
                }

                tooltipElement.appendChild(arrow);
                tooltipElement.appendChild(inner);

                // Make trigger element relatively positioned
                const originalPosition = window.getComputedStyle(el).position;
                if (originalPosition === 'static') {
                    el.style.position = 'relative';
                }

                // Append tooltip to trigger element
                el.appendChild(tooltipElement);
                el.setAttribute('aria-describedby', tooltipId);
            });
        };

        // Position tooltip using CSS
        const positionTooltip = () => {
            if (!tooltipElement) return;

            // Reset positioning
            tooltipElement.style.top = '';
            tooltipElement.style.bottom = '';
            tooltipElement.style.left = '';
            tooltipElement.style.right = '';
            tooltipElement.style.transform = '';

            switch (placement) {
                case 'top':
                    tooltipElement.style.bottom = '100%';
                    tooltipElement.style.left = '50%';
                    tooltipElement.style.transform = 'translateX(-50%)';
                    tooltipElement.style.marginBottom = '8px';
                    break;
                case 'bottom':
                    tooltipElement.style.top = '100%';
                    tooltipElement.style.left = '50%';
                    tooltipElement.style.transform = 'translateX(-50%)';
                    tooltipElement.style.marginTop = '8px';
                    break;
                case 'left':
                    tooltipElement.style.right = '100%';
                    tooltipElement.style.top = '50%';
                    tooltipElement.style.transform = 'translateY(-50%)';
                    tooltipElement.style.marginRight = '8px';
                    break;
                case 'right':
                    tooltipElement.style.left = '100%';
                    tooltipElement.style.top = '50%';
                    tooltipElement.style.transform = 'translateY(-50%)';
                    tooltipElement.style.marginLeft = '8px';
                    break;
            }
        };

        // Show/hide handlers
        const show = () => {
            if (!tooltipElement || !getContent) return;

            getContent((value: unknown) => {
                const content = String(value || '');
                if (!content) return;

                // Update content if needed
                const inner = tooltipElement!.querySelector('.tooltip-inner');
                if (inner) {
                    if (allowHtml) {
                        inner.innerHTML = content;
                    } else {
                        inner.textContent = content;
                    }
                }

                // Reposition
                positionTooltip();

                // Show tooltip
                showTooltip = true;
                tooltipElement!.classList.add('show');
                tooltipElement!.style.display = 'block';
            });
        };

        const hide = () => {
            if (!tooltipElement) return;
            showTooltip = false;
            tooltipElement.classList.remove('show');
            tooltipElement.style.display = 'none';
        };

        // Event listeners
        const handleMouseEnter = () => show();
        const handleMouseLeave = () => hide();
        const handleFocus = () => show();
        const handleBlur = () => hide();
        const handleClick = () => hide();

        el.addEventListener('mouseenter', handleMouseEnter);
        el.addEventListener('mouseleave', handleMouseLeave);
        el.addEventListener('focus', handleFocus, true);
        el.addEventListener('blur', handleBlur, true);
        el.addEventListener('click', handleClick);

        // Initialize tooltip
        createTooltip();

        // Update position on scroll/resize
        const updatePosition = () => {
            if (tooltipElement && showTooltip) {
                positionTooltip();
            }
        };
        window.addEventListener('scroll', updatePosition, true);
        window.addEventListener('resize', updatePosition);

        // Cleanup
        cleanup(() => {
            el.removeEventListener('mouseenter', handleMouseEnter);
            el.removeEventListener('mouseleave', handleMouseLeave);
            el.removeEventListener('focus', handleFocus, true);
            el.removeEventListener('blur', handleBlur, true);
            el.removeEventListener('click', handleClick);
            window.removeEventListener('scroll', updatePosition, true);
            window.removeEventListener('resize', updatePosition);

            if (tooltipElement) {
                tooltipElement.remove();
            }
            if (tooltipId) {
                el.removeAttribute('aria-describedby');
            }
        });
    });
}

/**
 * Initialize tooltips in a container (for HTMX swaps)
 * Converts data-bs-toggle="tooltip" to x-tooltip and initializes
 */
export function initializeTooltipsInContainer(container: HTMLElement): void {
    // Find elements with x-tooltip that need initialization
    const tooltipElements = container.querySelectorAll<HTMLElement>('[x-tooltip]');
    tooltipElements.forEach((el) => {
        if (!Alpine.$data(el)) {
            Alpine.initTree(el);
        }
    });

    // Auto-convert elements with data-bs-toggle="tooltip" or title attribute
    const autoTooltipElements = container.querySelectorAll<HTMLElement>(
        '[data-bs-toggle="tooltip"], [title]:not([x-tooltip]):not([data-bs-toggle="dropdown"])'
    );
    autoTooltipElements.forEach((el) => {
        if (el.hasAttribute('data-bs-toggle') || (el.title && !el.hasAttribute('x-tooltip'))) {
            const title = el.title || el.getAttribute('data-bs-original-title') || '';
            if (title) {
                el.removeAttribute('data-bs-toggle');
                el.removeAttribute('title');
                el.removeAttribute('data-bs-original-title');
                el.setAttribute('x-tooltip', `'${title.replace(/'/g, "\\'")}'`);
                Alpine.initTree(el);
            }
        }
    });
}

/**
 * Destroy tooltips in a container (for HTMX cleanup)
 */
export function destroyTooltipsInContainer(container: HTMLElement): void {
    // Remove tooltips from elements in container
    const tooltipElements = container.querySelectorAll<HTMLElement>('[x-tooltip]');
    tooltipElements.forEach((el) => {
        const tooltip = el.querySelector('.tooltip');
        if (tooltip) {
            tooltip.remove();
        }
        el.removeAttribute('aria-describedby');
    });

    // Remove orphaned tooltips
    document.querySelectorAll('.tooltip.show').forEach((tooltip) => {
        const id = tooltip.id;
        if (id) {
            const trigger = document.querySelector(`[aria-describedby="${id}"]`);
            if (!trigger || (container && !container.contains(trigger))) {
                tooltip.remove();
            }
        }
    });
}
