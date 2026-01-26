import Alpine from 'alpinejs';

/**
 * Settings Tabs Component
 * Handles tab navigation for settings pages with URL hash support
 * Replaces inline script in team_settings.html.j2
 */
export function registerSettingsTabs(): void {
    Alpine.data('settingsTabs', (availableTabs: string[]) => {
        return {
            availableTabs: availableTabs,
            activeTab: '',

            init() {
                // Get initial tab from URL hash or default to first tab
                this.activeTab = this.getCurrentTab();
                
                // Activate initial tab
                this.activateTab(this.activeTab);
                
                // Update active tab inputs on initialization
                this.updateActiveTabInputs();
            },

            getCurrentTab(): string {
                const hash = window.location.hash.substring(1);
                return this.availableTabs.includes(hash) ? hash : this.availableTabs[0];
            },

            activateTab(tabName: string) {
                if (!this.availableTabs.includes(tabName)) return;
                
                this.activeTab = tabName;
                
                // Update URL hash
                if (window.location.hash.substring(1) !== tabName) {
                    history.pushState(null, '', `#${tabName}`);
                }
                
                // Update active tab inputs
                this.updateActiveTabInputs();
            },

            handleTabClick(event: Event, tabName: string) {
                event.preventDefault();
                this.activateTab(tabName);
            },

            handleHashChange() {
                this.activeTab = this.getCurrentTab();
                this.updateActiveTabInputs();
            },

            updateActiveTabInputs() {
                // Update any hidden inputs with name="active_tab" within component scope
                const activeTabInputs = this.$el.querySelectorAll<HTMLInputElement>('input[name="active_tab"]');
                activeTabInputs.forEach(input => {
                    input.value = this.activeTab;
                });
            },

            isActiveTab(tabName: string): boolean {
                return this.activeTab === tabName;
            }
        };
    });
}
