import Alpine from 'alpinejs';

/**
 * Chart Tab Selector Component
 * Manages active chart type selection
 * 
 * Usage:
 *   <div x-data="chartTabSelector('timeline')">
 *     <button @click="activeChart = 'timeline'">Timeline</button>
 *     <button @click="activeChart = 'severity'">Severity</button>
 *   </div>
 */
export function registerChartTabSelector(): void {
    Alpine.data('chartTabSelector', (defaultType: string = 'timeline') => {
        return {
            activeChart: defaultType,

            setChartType(type: string): void {
                this.activeChart = type;
            },

            handleChartChange(): void {
                // Update chart when activeChart changes (called via x-effect in template)
                const value = this.activeChart;
                if (value) {
                    const container = this.$el.closest('.vulnerability-trends-section') as HTMLElement;
                    if (container) {
                        this.$nextTick(() => {
                            // Use store method if available, fallback to window function
                            try {
                                const chartsStore = this.$store?.charts as { initVulnerabilityChart?: (container: HTMLElement, chartType: string) => Promise<void> } | undefined;
                                if (chartsStore && typeof chartsStore.initVulnerabilityChart === 'function') {
                                    chartsStore.initVulnerabilityChart(container, value).catch((error: unknown) => {
                                        console.error('Failed to initialize chart:', error);
                                    });
                                } else if (typeof window !== 'undefined' && window.initVulnerabilityChart) {
                                    window.initVulnerabilityChart(container, value).catch((error: unknown) => {
                                        console.error('Failed to initialize chart:', error);
                                    });
                                }
                            } catch {
                                // Fallback to window function
                                if (typeof window !== 'undefined' && window.initVulnerabilityChart) {
                                    window.initVulnerabilityChart(container, value).catch((error: unknown) => {
                                        console.error('Failed to initialize chart:', error);
                                    });
                                }
                            }
                        });
                    }
                }
            }
        };
    });
}
