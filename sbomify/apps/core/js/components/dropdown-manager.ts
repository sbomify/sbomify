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
 *   <div x-data="dropdown" @click.away="close()">
 *     <button @click="toggle()" :aria-expanded="isOpen">Toggle</button>
 *     <div x-show="isOpen" class="dropdown-menu">...</div>
 *   </div>
 * Use @click.away on the dropdown root, not the menu, so item clicks are inside and not "away".
 */
export function registerDropdownManager(): void {
    // Track which dropdown is currently open (only one at a time)
    let openDropdown: HTMLElement | null = null;

    Alpine.data('dropdown', () => {
        return {
            isOpen: false,
            dropdownId: '',
            
            init() {
                this.dropdownId = `dropdown-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;

                const toggle = this.$el.querySelector('[data-bs-toggle="dropdown"], button, [role="button"]') as HTMLElement;
                const menu = this.$el.querySelector(
                    'ul[role="menu"], .dropdown-menu, .new-item-dropdown, .help-dropdown',
                ) as HTMLElement;

                if (!toggle || !menu) return;

                toggle.setAttribute('aria-haspopup', 'true');
                toggle.setAttribute('aria-expanded', 'false');
                toggle.setAttribute('id', `${this.dropdownId}-toggle`);
                menu.setAttribute('aria-labelledby', `${this.dropdownId}-toggle`);

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
                
                // Position dropdowns in navbar using fixed positioning to break out of stacking context
                const menu = this.$el.querySelector(
                    'ul[role="menu"], .dropdown-menu, .new-item-dropdown, .help-dropdown',
                ) as HTMLElement;
                if (menu && this.$el.closest('.navbar')) {
                    const rect = toggle.getBoundingClientRect();

                    // Use fixed positioning to break out of navbar's stacking context
                    menu.style.position = 'fixed';
                    menu.style.top = `${rect.bottom + 8}px`;
                    
                    // Position based on whether dropdown has 'right-0' class (right-aligned)
                    if (menu.classList.contains('right-0') || menu.style.textAlign === 'right') {
                        menu.style.right = `${window.innerWidth - rect.right}px`;
                        menu.style.left = 'auto';
                    } else {
                        menu.style.left = `${rect.left}px`;
                        menu.style.right = 'auto';
                    }
                    
                    menu.style.zIndex = '9999';
                    menu.classList.add('navbar-dropdown-fixed');
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
                
                // Clean up fixed positioning
                const menu = this.$el.querySelector(
                    'ul[role="menu"], .dropdown-menu, .new-item-dropdown, .help-dropdown',
                ) as HTMLElement;
                if (menu && menu.classList.contains('navbar-dropdown-fixed')) {
                    menu.style.position = '';
                    menu.style.top = '';
                    menu.style.left = '';
                    menu.style.right = '';
                    menu.style.zIndex = '';
                    menu.classList.remove('navbar-dropdown-fixed');
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

}
