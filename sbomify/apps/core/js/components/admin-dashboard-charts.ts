import Alpine from 'alpinejs';
import { Chart } from '../chart-setup';

interface ChartData {
    billingData: {
        labels: string[];
        datasets: Array<{ data: number[]; backgroundColor: string[]; borderWidth: number }>;
    };
    growthData: {
        labels: string[];
        data: number[];
    };
    funnelData: {
        labels: string[];
        data: number[];
        total: number;
    };
    healthData: {
        labels: string[];
        data: number[];
    };
    usersPerWorkspaceData: {
        labels: string[];
        data: number[];
    };
    componentsData: {
        labels: string[];
        data: number[];
    };
}

interface AdminDashboardChartsData {
    charts: ChartData;
    chartsInitialized: boolean;
    $el: HTMLElement;
    init(): void;
    initializeCharts(): void;
    handleChartError(error: unknown): void;
    showChart(chartId: string): void;
}

/**
 * Admin Dashboard Charts Component
 * Handles Chart.js initialization for admin dashboard
 */
export function registerAdminDashboardCharts(): void {
    Alpine.data('adminDashboardCharts', (chartsData: ChartData): AdminDashboardChartsData => {
        return {
            charts: chartsData,
            chartsInitialized: false,
            $el: {} as HTMLElement, // Will be set by Alpine
            
            init() {
                if (this.chartsInitialized) return;
                
                try {
                    this.initializeCharts();
                    this.chartsInitialized = true;
                } catch (error) {
                    console.error('Error initializing charts:', error);
                    this.handleChartError(error);
                }
            },
            
            initializeCharts() {
                // Billing Distribution (Doughnut Chart)
                const billingCanvas = this.$el.querySelector('#billingChart') as HTMLCanvasElement;
                if (billingCanvas) {
                    new Chart(billingCanvas, {
                        type: 'doughnut',
                        data: this.charts.billingData,
                        options: {
                            responsive: true,
                            maintainAspectRatio: false,
                            plugins: {
                                legend: {
                                    position: 'bottom'
                                }
                            },
                            cutout: '60%'
                        }
                    });
                    this.showChart('billingChart');
                }
                
                // User Growth Trend (Line Chart)
                const growthCanvas = this.$el.querySelector('#growthChart') as HTMLCanvasElement;
                if (growthCanvas) {
                    new Chart(growthCanvas, {
                        type: 'line',
                        data: {
                            labels: this.charts.growthData.labels,
                            datasets: [{
                                label: 'New Users',
                                data: this.charts.growthData.data,
                                borderColor: '#10B981',
                                backgroundColor: 'rgba(16, 185, 129, 0.1)',
                                fill: true,
                                tension: 0.4,
                                pointRadius: 3,
                                pointBackgroundColor: '#10B981'
                            }]
                        },
                        options: {
                            responsive: true,
                            maintainAspectRatio: false,
                            plugins: {
                                legend: {
                                    display: false
                                }
                            },
                            scales: {
                                y: {
                                    beginAtZero: true,
                                    ticks: {
                                        stepSize: 1
                                    }
                                },
                                x: {
                                    ticks: {
                                        maxRotation: 45,
                                        minRotation: 45
                                    }
                                }
                            }
                        }
                    });
                    this.showChart('growthChart');
                }
                
                // Onboarding Funnel (Horizontal Bar Chart)
                const funnelCanvas = this.$el.querySelector('#funnelChart') as HTMLCanvasElement;
                if (funnelCanvas) {
                    new Chart(funnelCanvas, {
                        type: 'bar',
                        data: {
                            labels: this.charts.funnelData.labels,
                            datasets: [{
                                label: 'Users',
                                data: this.charts.funnelData.data,
                                backgroundColor: ['#6366F1', '#8B5CF6', '#A855F7', '#EC4899'],
                                borderRadius: 4
                            }]
                        },
                        options: {
                            indexAxis: 'y',
                            responsive: true,
                            maintainAspectRatio: false,
                            plugins: {
                                legend: {
                                    display: false
                                },
                                tooltip: {
                                    callbacks: {
                                        label: (context) => {
                                            const total = this.charts.funnelData.total;
                                            const value = context.raw as number;
                                            const percentage = total > 0 ? Math.round((value / total) * 100) : 0;
                                            return `${value} users (${percentage}%)`;
                                        }
                                    }
                                }
                            },
                            scales: {
                                x: {
                                    beginAtZero: true
                                }
                            }
                        }
                    });
                    this.showChart('funnelChart');
                }
                
                // Product Health (Bar Chart)
                const healthCanvas = this.$el.querySelector('#healthChart') as HTMLCanvasElement;
                if (healthCanvas) {
                    new Chart(healthCanvas, {
                        type: 'bar',
                        data: {
                            labels: this.charts.healthData.labels,
                            datasets: [{
                                label: 'Workspaces',
                                data: this.charts.healthData.data,
                                backgroundColor: ['#10B981', '#F59E0B', '#3B82F6', '#8B5CF6'],
                                borderRadius: 4
                            }]
                        },
                        options: {
                            responsive: true,
                            maintainAspectRatio: false,
                            plugins: {
                                legend: {
                                    display: false
                                }
                            },
                            scales: {
                                y: {
                                    beginAtZero: true,
                                    ticks: {
                                        stepSize: 1
                                    }
                                }
                            }
                        }
                    });
                    this.showChart('healthChart');
                }
                
                // Users per Workspace Chart
                const usersPerWorkspaceCanvas = this.$el.querySelector('#usersPerWorkspaceChart') as HTMLCanvasElement;
                if (usersPerWorkspaceCanvas) {
                    new Chart(usersPerWorkspaceCanvas, {
                        type: 'bar',
                        data: {
                            labels: this.charts.usersPerWorkspaceData.labels,
                            datasets: [{
                                label: 'Users',
                                data: this.charts.usersPerWorkspaceData.data,
                                backgroundColor: '#4bc0c0',
                                borderRadius: 4
                            }]
                        },
                        options: {
                            responsive: true,
                            maintainAspectRatio: false,
                            plugins: {
                                legend: {
                                    display: false
                                }
                            },
                            scales: {
                                y: {
                                    beginAtZero: true,
                                    ticks: {
                                        stepSize: 1
                                    }
                                },
                                x: {
                                    ticks: {
                                        maxRotation: 45,
                                        minRotation: 45
                                    }
                                }
                            }
                        }
                    });
                    this.showChart('usersPerWorkspaceChart');
                }
                
                // Components Overview Bar Chart
                const componentsCanvas = this.$el.querySelector('#componentsChart') as HTMLCanvasElement;
                if (componentsCanvas) {
                    new Chart(componentsCanvas, {
                        type: 'bar',
                        data: {
                            labels: this.charts.componentsData.labels,
                            datasets: [{
                                label: 'Count',
                                data: this.charts.componentsData.data,
                                backgroundColor: ['#ff6384', '#36a2eb', '#ffcd56', '#4bc0c0', '#9966ff'],
                                borderRadius: 4
                            }]
                        },
                        options: {
                            responsive: true,
                            maintainAspectRatio: false,
                            plugins: {
                                legend: {
                                    display: false
                                }
                            },
                            scales: {
                                y: {
                                    beginAtZero: true,
                                    ticks: {
                                        stepSize: 1
                                    }
                                }
                            }
                        }
                    });
                    this.showChart('componentsChart');
                }
            },
            
            showChart(canvasId: string) {
                const canvas = this.$el.querySelector(`#${canvasId}`) as HTMLCanvasElement;
                if (!canvas) return;
                const loading = canvas.previousElementSibling as HTMLElement;
                canvas.classList.remove('hidden');
                if (loading) loading.style.display = 'none';
            },
            
            handleChartError(error: unknown) {
                const container = this.$el.querySelector('.dashboard-container') as HTMLElement;
                if (container) {
                    const errorMessage = error instanceof Error ? error.message : String(error);
                    container.innerHTML = `
                        <div class="error-message">
                            <h3>Error Loading Dashboard</h3>
                            <p>There was an error loading the dashboard charts. Please try refreshing the page.</p>
                            <p style="font-size: 0.8rem; color: #666;">Error: ${errorMessage}</p>
                        </div>
                    `;
                }
            }
        };
    });
}
