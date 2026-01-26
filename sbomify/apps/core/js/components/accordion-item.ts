import Alpine from 'alpinejs';

/**
 * Accordion Item Component
 * For accordion items with expand/collapse state
 * 
 * Usage:
 *   <div x-data="accordionItem(false)">
 *     <button @click="expanded = !expanded">Toggle</button>
 *     <div x-show="expanded" x-collapse>Content</div>
 *   </div>
 */
export function registerAccordionItem(): void {
    Alpine.data('accordionItem', (defaultExpanded: boolean = false) => {
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
