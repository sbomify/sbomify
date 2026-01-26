import Alpine from 'alpinejs';

/**
 * Collapsible Section Component
 * Simple expand/collapse state management
 * 
 * Usage:
 *   <div x-data="collapsibleSection(true)">
 *     <button @click="expanded = !expanded">Toggle</button>
 *     <div x-show="expanded" x-collapse>Content</div>
 *   </div>
 */
export function registerCollapsibleSection(): void {
    Alpine.data('collapsibleSection', (defaultExpanded: boolean = false) => {
        return {
            expanded: defaultExpanded,
            
            toggle(): void {
                this.expanded = !this.expanded;
            },
            
            expand(): void {
                this.expanded = true;
            },
            
            collapse(): void {
                this.expanded = false;
            }
        };
    });
}
