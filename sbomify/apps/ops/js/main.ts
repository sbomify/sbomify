import '../../core/js/chart-setup';
import { initOpsCharts } from './ops-charts';

function start(): void {
  initOpsCharts();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', start);
} else {
  start();
}
