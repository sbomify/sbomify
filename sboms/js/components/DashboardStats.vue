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
  </div>
</template>

<script setup lang="ts">
  // Parent component for toggling between meta info display and edit components.
  import $axios from '../../../core/js/utils';
  import { isAxiosError } from 'axios';
  import { ref, onMounted, computed } from 'vue';
  import { showError } from '../../../core/js/alerts';

  import type { DashboardStats } from '../type_defs.d.ts';

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
    total_products: 0,
    total_projects: 0,
    total_components: 0,
    latest_uploads: [],
  });

  const getStats = async () => {
    let apiUrl = '/api/v1/sboms/dashboard/summary/';

    if (props.itemType === 'component' && props.itemId) {
      apiUrl += `?component_id=${props.itemId}`;
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

  onMounted(() => {
    getStats();
  });
</script>

<style scoped>
.sbom-item {
  cursor: pointer;
}
</style>