import {
    Chart,
    CategoryScale,
    LinearScale,
    BarElement,
    LineElement,
    PointElement,
    ArcElement,
    LineController,
    BarController,
    DoughnutController,
    Filler,
    Title,
    Tooltip,
    Legend,
} from 'chart.js';

// Register Chart.js components
Chart.register(
    CategoryScale,
    LinearScale,
    BarElement,
    LineElement,
    PointElement,
    ArcElement,
    LineController,
    BarController,
    DoughnutController,
    Filler,
    Title,
    Tooltip,
    Legend
);

// Make Chart available globally
declare global {
    interface Window {
        Chart: typeof Chart;
    }
}

window.Chart = Chart;

export { Chart };
