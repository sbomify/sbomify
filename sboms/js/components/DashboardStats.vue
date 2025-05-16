<template>
  <div class="container-fluid p-0">
    <div v-if="props.itemType !== 'component'" class="row">
      <div v-if="stats.total_products !== null" :class="sizeClasses">
        <div class="card">
          <div class="card-header">
            <h5 class="card-title mb-0">Total Products</h5>
          </div>
          <div class="card-body text-center">
            <h1 class="display-4">{{ stats.total_products }}</h1>
          </div>
        </div>
      </div>

      <div v-if="stats.total_projects !== null" :class="sizeClasses">
        <div class="card">
          <div class="card-header">
            <h5 class="card-title mb-0">Total Projects</h5>
          </div>
          <div class="card-body text-center">
            <h1 class="display-4">{{ stats.total_projects }}</h1>
          </div>
        </div>
      </div>

      <div v-if="stats.total_components !== null" :class="sizeClasses">
        <div class="card">
          <div class="card-header">
            <h5 class="card-title mb-0">Total Components</h5>
          </div>
          <div class="card-body text-center">
            <h1 class="display-4">{{ stats.total_components }}</h1>
          </div>
        </div>
      </div>
    </div>

    <div class="row">
      <div :class="orderClasses">
        <div class="card">
          <div class="card-header">
            <h5 class="card-title mb-0">Latest Component Uploads</h5>
          </div>

            <table v-if="stats.component_uploads && stats.component_uploads.length > 0" class="table table-striped">
              <thead>
                <tr>
                  <th scope="col">Component</th>
                  <th scope="col">Version</th>
                  <th scope="col">Uploaded At</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="component in stats.component_uploads" :key="component.sbom_id" class="sbom-item"
                  @click="component.sbom_id && openSBOMPage(component.sbom_id)">
                  <td>{{ component.component_name }}</td>
                  <td>
                    <span v-if="component.sbom_version">
                    {{ component.sbom_version.length > 12 ? '...' + component.sbom_version.slice(-12) : component.sbom_version }}
                    </span>
                  </td>
                  <td>
                    <span v-if="component.sbom_created_at">
                    {{ new Date(component.sbom_created_at).toLocaleString('en-US', { month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: 'numeric' }) }}
                    </span>
                  </td>
                </tr>
              </tbody>
            </table>

            <p v-else class="pt-3 text-center">No SBOMs uploaded yet</p>
        </div>
      </div>

      <div v-if="Object.keys(stats.license_count || {}).length > 0" :class="[orderClasses, props.itemType === undefined ? '' : 'order-md-first']" >
        <div class="card">
          <div class="card-body">
            <h4 class="d-flex justify-content-between align-items-center mb-4" style="cursor: pointer;" @click="toggleStats">
              Statistics
              <svg v-if="!statsExpanded" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"></polyline></svg>
              <svg v-if="statsExpanded" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"></polyline></svg>
            </h4>
            <div v-if="statsExpanded" class="mt-3">
              <h6 class="text-muted mb-3">License Distribution</h6>
              <div class="chart-wrapper" :style="{ height: dynamicChartHeight, maxHeight: dynamicChartHeight, position: 'relative' }">
                <Bar
                  v-if="chartData.labels.length > 0"
                  :data="chartData"
                  :options="chartOptions"
                />
              </div>
              <p v-if="chartData.labels.length === 0 && Object.keys(stats.license_count || {}).length > 0" class="text-center text-muted">No license data to display after filtering.</p>
              <p v-else-if="Object.keys(stats.license_count || {}).length === 0" class="text-center text-muted">No license data available</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>

</template>

<script setup lang="ts">
  // Parent component for toggling between meta info display and edit components.
  import $axios from '../../../core/js/utils';
  import { isAxiosError } from 'axios';
  import { ref, onMounted, computed } from 'vue';
  import {
    Chart as ChartJS,
    CategoryScale,
    LinearScale,
    BarElement,
    Title,
    Tooltip,
    Legend,
    type TooltipItem
  } from 'chart.js';
  import { Bar } from 'vue-chartjs';
  import { showError } from '../../../core/js/alerts';

  import type { DashboardStats } from '../type_defs.d.ts';

  ChartJS.register(
    CategoryScale,
    LinearScale,
    BarElement,
    Title,
    Tooltip,
    Legend
  );

  const props = defineProps<{
    size?: 'small' | 'large';
    teamKey?: string;
    itemType?: string;
    itemId?: string;
  }>();

  const sizeClasses = computed(() => {
    return props.size === 'small' ? 'col-md-3' : 'col-md-6';
  });

  const stats = ref<DashboardStats>({
    total_components: 0,
    total_public_components: 0,
    total_private_components: 0,
    total_users: 0,
    total_products: 0,
    total_projects: 0,
    component_uploads: [],
    license_count: {}
  });

  const statsExpanded = ref(true);

  const toggleStats = () => {
    statsExpanded.value = !statsExpanded.value;
  };

  const orderClasses = computed(() => {
    const classes = [];
    classes.push(props.itemType === undefined ? 'col-md-6' : 'col-md-12');
    return classes;
  });

  const chartData = computed(() => {
    if (!stats.value.license_count) return { labels: [], datasets: [] };

    // Sort licenses by count and get top 15
    const sortedLicenses = Object.entries(stats.value.license_count)
      .sort(([, a], [, b]) => (b as number) - (a as number));

    const TOP_N = 15;
    let labels: string[] = [];
    let data: number[] = [];

    if (sortedLicenses.length > TOP_N) {
      // Take top N licenses
      labels = sortedLicenses.slice(0, TOP_N).map(([name]) => name);
      data = sortedLicenses.slice(0, TOP_N).map(([, count]) => count as number);

      // Add "Others" category with sum of remaining
      const othersSum = sortedLicenses.slice(TOP_N)
        .reduce((sum, [, count]) => sum + (count as number), 0);
      if (othersSum > 0) {
        labels.push('Others');
        data.push(othersSum);
      }
    } else {
      labels = sortedLicenses.map(([name]) => name);
      data = sortedLicenses.map(([, count]) => count as number);
    }

    return {
      labels,
      datasets: [{
        backgroundColor: '#36A2EB',
        data,
        barThickness: 16,
        maxBarThickness: 20
      }]
    };
  });

  const chartOptions = computed(() => ({
    responsive: true,
    maintainAspectRatio: false,
    indexAxis: 'y' as 'x' | 'y' | undefined,
    layout: {
      padding: {
        left: 10,
        right: 20,
        top: 5,
        bottom: 5
      }
    },
    plugins: {
      legend: {
        display: false
      },
      tooltip: {
        callbacks: {
          label: function(context: TooltipItem<'bar'>) {
            const data = context.dataset.data as number[];
            const total = data.reduce((a, b) => a + b, 0);
            const value = context.raw as number;
            const percentage = total > 0 ? ((value / total) * 100).toFixed(1) : 0;
            return `${value} (${percentage}%)`;
          }
        }
      }
    },
    scales: {
      x: {
        beginAtZero: true,
        title: {
          display: true,
          text: 'Number of Components'
        },
        grid: {
          display: true,
        }
      },
      y: {
        ticks: {
          autoSkip: false,
          font: {
            size: 11
          }
        },
        grid: {
          display: false,
        }
      }
    }
  }));

  const dynamicChartHeight = computed(() => {
    const numLabels = chartData.value.labels ? chartData.value.labels.length : 0;

    if (numLabels === 0) {
      return '150px';
    }

    const barThickness = 20;
    const paddingBetweenBars = 10;
    const xAxisHeightEstimate = 60;

    let calculatedHeight = (numLabels * barThickness) + (Math.max(0, numLabels - 1) * paddingBetweenBars) + xAxisHeightEstimate;

    const minHeight = 120;
    const maxHeight = 400;

    calculatedHeight = Math.min(maxHeight, Math.max(minHeight, calculatedHeight));

    return `${calculatedHeight}px`;
  });

  const getStats = async () => {
    let apiUrl = '/api/v1/sboms/stats';
    if (props.teamKey !== undefined) {
      apiUrl += `?team_key=${props.teamKey}`;
    } else {
      if (props.itemType !== undefined) {
        apiUrl += `?item_type=${props.itemType}`;
        if (props.itemId !== undefined) {
          apiUrl += `&item_id=${props.itemId}`;
        }
      }
    }

    try {
      const response = await $axios.get(apiUrl);
      if (response.status < 200 || response.status >= 300) {
        throw new Error('Network response was not ok. ' + response.statusText);
      }
      stats.value = response.data;
    } catch (error) {
      console.log(error);
      if (isAxiosError(error)) {
        showError(`${error.response?.status} - ${error.response?.statusText}: ${error.response?.data?.detail[0].msg}`);
      } else {
        showError('Failed to load stats');
      }
    }
  };

  const openSBOMPage = (sbomId: string) => {
    location.href = '/sboms/sbom/' + sbomId;
  };

  onMounted(() => {
    getStats();
  });
</script>

<style scoped>
.sbom-item {
  cursor: pointer;
}
</style>