<template>
  <div class="float-end" style="display:inline-flex">
    <CopyableValue v-if="isPublic" class="float-end pe-2" :value="props.publicUrl" title="Copy public URL" hide-value></CopyableValue>

    <div class="form-check form-switch">
      <label class="form-check-label" for="togglePublicStatus">Allow public access</label>
      <input id="togglePublicStatus" class="form-check-input" type="checkbox" :checked="isPublic" :disabled="isLoading" @click="togglePublicStatus()">
    </div>
  </div>
</template>

<script setup lang="ts">
  import { ref, onMounted } from 'vue';
  import $axios from '../../../core/js/utils';
  import CopyableValue from '../../../core/js/components/CopyableValue.vue';

  interface Props {
    itemType: string;
    itemId: string;
    publicUrl: string;
  }

  // Type declaration for Django messaging system
  interface DjangoMessaging {
    addMessage: (type: string, message: string) => void;
  }

  interface WindowWithDjango extends Window {
    django?: DjangoMessaging;
  }

  interface ApiErrorResponse {
    response?: {
      status: number;
      data?: {
        detail?: string;
      };
    };
  }

  const props = defineProps<Props>()

  const isPublic = ref(false);
  const isLoading = ref(false);
  const apiUrl = '/api/v1/sboms/' + props.itemType + '/' + props.itemId + '/public_status';

  onMounted(async () => {
    try {
      const response = await $axios.get(apiUrl);
      if (response.status < 200 || response.status >= 300) {
        throw new Error('Network response was not ok. ' + response.statusText);
      }
      isPublic.value = response.data.is_public;
    } catch (error) {
      console.error('Failed to load public status:', error);
      showError('Failed to load public status');
    }
  });

  const togglePublicStatus = async () => {
    const newPublicStatus = !isPublic.value;
    isLoading.value = true;

    const data = {
      is_public: newPublicStatus
    }

    try {
      const response = await $axios.patch(apiUrl, data);

      if (response.status < 200 || response.status >= 300) {
        throw new Error('Network response was not ok. ' + response.statusText);
      }

      isPublic.value = response.data.is_public;

      // Show success message
      if (isPublic.value) {
        showSuccess(`${props.itemType.charAt(0).toUpperCase() + props.itemType.slice(1)} is now public`);
      } else {
        showSuccess(`${props.itemType.charAt(0).toUpperCase() + props.itemType.slice(1)} is now private`);
      }

    } catch (error) {
      const apiError = error as ApiErrorResponse;
      console.error('Failed to toggle public status:', error);

      // Handle specific error cases
      if (apiError.response?.status === 403) {
        const errorMessage = apiError.response.data?.detail || 'Permission denied';
        showError(errorMessage);
      } else if (apiError.response?.status === 400) {
        const errorMessage = apiError.response.data?.detail || 'Invalid request';
        showError(errorMessage);
      } else {
        showError('Failed to update public status. Please try again.');
      }
    } finally {
      isLoading.value = false;
    }
  }

  // Helper functions for showing notifications
  const showError = (message: string) => {
    // Use Django's messaging system if available
    const windowWithDjango = window as WindowWithDjango;
    if (windowWithDjango.django && windowWithDjango.django.addMessage) {
      windowWithDjango.django.addMessage('error', message);
    } else {
      // Fallback to alert
      alert(`Error: ${message}`);
    }
  };

  const showSuccess = (message: string) => {
    // Use Django's messaging system if available
    const windowWithDjango = window as WindowWithDjango;
    if (windowWithDjango.django && windowWithDjango.django.addMessage) {
      windowWithDjango.django.addMessage('success', message);
    }
    // Note: No fallback alert for success messages to avoid spam
  };

</script>

<style scoped>
</style>
