import Alpine from 'alpinejs';

/**
 * Component Type Sync
 * Syncs component type select with global toggle visibility
 */
export function registerComponentTypeSync(): void {
    Alpine.data('componentTypeSync', () => {
        return {
            componentType: 'sbom',
            
            get isDocument(): boolean {
                return this.componentType === 'document';
            },
            
            init() {
                // Get initial value from select if it exists
                const select = (this.$refs as { componentTypeSelect?: HTMLSelectElement }).componentTypeSelect;
                if (select) {
                    this.componentType = select.value;
                }
            },
            
            handleTypeChange() {
                const select = (this.$refs as { componentTypeSelect?: HTMLSelectElement }).componentTypeSelect;
                const globalToggle = (this.$refs as { componentIsGlobalToggle?: HTMLInputElement }).componentIsGlobalToggle;
                
                if (select) {
                    this.componentType = select.value;
                }
                
                // Uncheck global toggle if not document
                if (!this.isDocument && globalToggle) {
                    globalToggle.checked = false;
                }
            }
        };
    });
}
