import Alpine from 'alpinejs';

/**
 * SBOM Vulnerabilities Auto-Refresh Component
 * Handles auto-refresh when vulnerability scan is processing
 */
export function registerSbomVulnerabilitiesRefresh(): void {
    Alpine.data('sbomVulnerabilitiesRefresh', (refreshInterval: number = 30000) => {
        return {
            refreshInterval,
            timer: null as ReturnType<typeof setTimeout> | null,

            init() {
                // Only start auto-refresh if we're in processing state
                // This is determined by the presence of the processing alert
                const processingAlert = this.$el.querySelector('.alert-info');
                if (processingAlert) {
                    this.startTimer();
                }
            },

            startTimer() {
                this.clearTimer();
                this.timer = setTimeout(() => {
                    window.location.reload();
                }, this.refreshInterval);
            },

            clearTimer() {
                if (this.timer) {
                    clearTimeout(this.timer);
                    this.timer = null;
                }
            },

            handleRefresh() {
                window.location.reload();
            },

            destroy() {
                this.clearTimer();
            }
        };
    });
}
