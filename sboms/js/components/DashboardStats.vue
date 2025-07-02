<template>
  <div class="container-fluid p-0">
    <div class="row">
      <!-- Products: Show on main dashboard and product pages -->
      <div v-if="shouldShowProducts" :class="sizeClasses">
        <StatCard
          :title="getProductTitle()"
          :value="stats.total_products"
          :loading="isLoading"
          :error="errorMessage"
          :size="cardSize"
          color-scheme="default"
        />
      </div>

      <!-- Projects: Show on main dashboard, product pages, and project pages -->
      <div v-if="shouldShowProjects" :class="sizeClasses">
        <StatCard
          :title="getProjectTitle()"
          :value="stats.total_projects"
          :loading="isLoading"
          :error="errorMessage"
          :size="cardSize"
          color-scheme="default"
        />
      </div>

      <!-- Components: Show on main dashboard, product pages, project pages, and component pages -->
      <div v-if="shouldShowComponents" :class="sizeClasses">
        <StatCard
          :title="getComponentTitle()"
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

import type { DashboardStats } from '../../../core/js/type_defs.d.ts';

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
  total_products: 0,
  total_projects: 0,
  total_components: 0,
  latest_uploads: [],
});

// Determine what stats to show based on context
const shouldShowProducts = computed(() => {
  // Only show products on main dashboard (no specific item context)
  return !props.itemType;
});

const shouldShowProjects = computed(() => {
  // Show projects on main dashboard and when viewing a specific product
  return !props.itemType || props.itemType === 'product';
});

const shouldShowComponents = computed(() => {
  // Show components on main dashboard, product pages, and project pages
  // Don't show on component pages since it would always be 1
  return !props.itemType || props.itemType === 'product' || props.itemType === 'project';
});

// Dynamic titles based on context
const getProductTitle = () => {
  return 'Total Products';
};

const getProjectTitle = () => {
  if (props.itemType === 'product') {
    return 'Projects in Product';
  }
  return 'Total Projects';
};

const getComponentTitle = () => {
  if (props.itemType === 'product') {
    return 'Components in Product';
  } else if (props.itemType === 'project') {
    return 'Components in Project';
  }
  return 'Total Components';
};

const getStats = async () => {
  isLoading.value = true;
  errorMessage.value = null;

      let apiUrl = '/api/v1/dashboard/summary';
  const params = new URLSearchParams();

  // Add appropriate filter parameters based on context
  if (props.itemType === 'product' && props.itemId) {
    params.append('product_id', props.itemId);
  } else if (props.itemType === 'project' && props.itemId) {
    params.append('project_id', props.itemId);
  } else if (props.itemType === 'component' && props.itemId) {
    params.append('component_id', props.itemId);
  }

  if (params.toString()) {
    apiUrl += `?${params.toString()}`;
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