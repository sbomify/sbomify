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

            <table v-if="stats.latest_uploads && stats.latest_uploads.length > 0" class="table table-striped">
              <thead>
                <tr>
                  <th scope="col">Component</th>
                  <th scope="col">Version</th>
                  <th scope="col">Uploaded At</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(component, index) in stats.latest_uploads" :key="index" class="sbom-item">
                  <td>{{ component.component_name }}</td>
                  <td>
                    <span v-if="component.sbom_version">
                    {{ component.sbom_version.length > 12 ? '...' + component.sbom_version.slice(-12) : component.sbom_version }}
                    </span>
                  </td>
                  <td>
                    <span v-if="component.created_at">
                    {{ new Date(component.created_at).toLocaleString('en-US', { month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: 'numeric' }) }}
                    </span>
                  </td>
                </tr>
              </tbody>
            </table>

            <p v-else class="pt-3 text-center">No SBOMs uploaded yet</p>
        </div>
      </div>

      <!-- License chart and statistics section removed -->
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

  const orderClasses = computed(() => {
    const classes = [];
    classes.push(props.itemType === undefined ? 'col-md-6' : 'col-md-12');
    return classes;
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