import Alpine from 'alpinejs';

/**
 * Dropdown Manager Component
 * 
 * Global Setup File with Component Cleanup
 * 
 * This file sets up application-wide dropdown management. The global event listeners
 * are intentionally global and persist for the app lifetime. However, individual
 * dropdown components have destroy() methods to clean up their own listeners.
 * 
 * Global setup files vs Component-scoped:
 * - Global: Application-wide, persists for app lifetime, no cleanup needed
 * - Component-scoped: Per-component, requires destroy() cleanup
 * 
 * This file is a hybrid: global setup with per-component cleanup.
 * 
 * Pure Alpine.js dropdown implementation replacing Bootstrap JS
 * 
 * Usage:
 *   <div x-data="dropdown" class="dropdown">
 *     <button @click="toggle()" :aria-expanded="isOpen">Toggle</button>
 *     <div x-show="isOpen" @click.away="close()" class="dropdown-menu">...</div>
 *   </div>
 */
export function registerDropdownManager(): void {
    // Track which dropdown is currently open (only one at a time)
    let openDropdown: HTMLElement | null = null;

    Alpine.data('dropdown', () => {
        return {
            isOpen: false,
            dropdownId: '',
            
            init() {
                // Generate unique ID for ARIA associations
                this.dropdownId = `dropdown-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
                
                const toggle = this.$el.querySelector('[data-bs-toggle="dropdown"], button, [role="button"]') as HTMLElement;
                const menu = this.$el.querySelector('.dropdown-menu') as HTMLElement;
                
                if (!toggle || !menu) return;

                // Set ARIA attributes
                toggle.setAttribute('aria-haspopup', 'true');
                toggle.setAttribute('aria-expanded', 'false');
                toggle.setAttribute('id', `${this.dropdownId}-toggle`);
                menu.setAttribute('aria-labelledby', `${this.dropdownId}-toggle`);
                
                // Remove data-bs-toggle to prevent Bootstrap initialization
                toggle.removeAttribute('data-bs-toggle');
            },
            
            toggle() {
                if (this.isOpen) {
                    this.close();
                } else {
                    this.open();
                }
            },
            
            open() {
                // Close other open dropdowns
                if (openDropdown && openDropdown !== this.$el) {
                    const otherData = Alpine.$data(openDropdown) as { close?: () => void } | null;
                    if (otherData && typeof otherData.close === 'function') {
                        otherData.close();
                    }
                }
                
                this.isOpen = true;
                openDropdown = this.$el;
                
                const toggle = this.$el.querySelector('[id$="-toggle"]') as HTMLElement;
                if (toggle) {
                    toggle.setAttribute('aria-expanded', 'true');
                    toggle.focus();
                }
            },
            
            close() {
                this.isOpen = false;
                if (openDropdown === this.$el) {
                    openDropdown = null;
                }
                
                const toggle = this.$el.querySelector('[id$="-toggle"]') as HTMLElement;
                if (toggle) {
                    toggle.setAttribute('aria-expanded', 'false');
                }
            },
            
            destroy() {
                if (openDropdown === this.$el) {
                    openDropdown = null;
                }
                this.isOpen = false;
            }
        };
    });
    
    // Global Escape key handler to close open dropdowns
    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && openDropdown) {
            const dropdownData = Alpine.$data(openDropdown) as { close?: () => void } | null;
            if (dropdownData && typeof dropdownData.close === 'function') {
                dropdownData.close();
                
                // Return focus to toggle button
                const toggle = openDropdown.querySelector('[id$="-toggle"]') as HTMLElement;
                if (toggle) {
                    toggle.focus();
                }
            }
        }
    });

    // Global focus handler to close dropdowns when focus leaves
    document.addEventListener('focusin', (event) => {
        if (!openDropdown) return;
        
        const target = event.target as HTMLElement;
        const isInsideDropdown = openDropdown.contains(target);
        
        if (!isInsideDropdown) {
            const dropdownData = Alpine.$data(openDropdown) as { close?: () => void } | null;
            if (dropdownData && typeof dropdownData.close === 'function') {
                dropdownData.close();
            }
        }
    });
}
