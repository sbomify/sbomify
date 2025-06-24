<template>
  <div class="container-fluid p-0">
    <div v-if="props.itemType !== 'component'" class="row">
      <div v-if="shouldShowStat('total_products')" :class="sizeClasses">
        <StatCard
          title="Total Products"
          :value="stats.total_products"
          :loading="isLoading"
          :error="errorMessage"
          :size="cardSize"
          color-scheme="default"
        />
      </div>

      <div v-if="shouldShowStat('total_projects')" :class="sizeClasses">
        <StatCard
          title="Total Projects"
          :value="stats.total_projects"
          :loading="isLoading"
          :error="errorMessage"
          :size="cardSize"
          color-scheme="default"
        />
      </div>

      <div v-if="shouldShowStat('total_components')" :class="sizeClasses">
        <StatCard
          title="Total Components"
          :value="stats.total_components"
          :loading="isLoading"
          :error="errorMessage"
          :size="cardSize"
          color-scheme="default"
        />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import $axios from '../../../core/js/utils';
import { isAxiosError } from 'axios';
import { ref, onMounted, computed } from 'vue';
import { showError } from '../../../core/js/alerts';
import StatCard from '../../../core/js/components/StatCard.vue';

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

const cardSize = computed(() => {
  return props.size === 'small' ? 'small' : 'medium';
});

const isLoading = ref(true);
const errorMessage = ref<string | null>(null);

const stats = ref<DashboardStats>({
  total_products: null,
  total_projects: null,
  total_components: null,
  latest_uploads: [],
});

const shouldShowStat = (statKey: keyof DashboardStats) => {
  // Show if not loading and stat is not null
  if (isLoading.value) return true; // Show loading state
  if (errorMessage.value) return true; // Show error state

  const statValue = stats.value[statKey];
  return statValue !== null && statValue !== undefined;
};

const getStats = async () => {
  isLoading.value = true;
  errorMessage.value = null;

  let apiUrl = '/api/v1/sboms/dashboard/summary/';

  if (props.itemType && props.itemId) {
    apiUrl += `?${props.itemType}_id=${props.itemId}`;
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
      const errorMsg = `${error.response?.status} - ${error.response?.statusText}: ${error.response?.data?.detail?.[0]?.msg || 'Unknown error'}`;
      errorMessage.value = errorMsg;
      showError(errorMsg);
    } else {
      errorMessage.value = 'Failed to load stats';
      showError('Failed to load stats');
    }
  } finally {
    isLoading.value = false;
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