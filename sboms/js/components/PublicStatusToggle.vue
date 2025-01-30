<template>
  <div class="float-end" style="display:inline-flex">
    <CopyableValue v-if="isPublic" class="float-end pe-2" :value="props.publicUrl" title="Copy public URL" hide-value></CopyableValue>

    <div class="form-check form-switch">
      <label class="form-check-label" for="togglePublicStatus">Allow public access</label>
      <input id="togglePublicStatus" class="form-check-input" type="checkbox" :checked="isPublic" @click="togglePublicStatus()">
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

  const props = defineProps<Props>()

  const isPublic = ref(false);
  const apiUrl = '/api/v1/sboms/' + props.itemType + '/' + props.itemId + '/public_status';

  onMounted(async () => {
    try {
      const response = await $axios.get(apiUrl);
      if (response.status < 200 || response.status >= 300) {
        throw new Error('Network response was not ok. ' + response.statusText);
      }
      isPublic.value = response.data.is_public;
    } catch (error) {
      console.log(error)
    }
  });

  const togglePublicStatus = async () => {
    const data = {
      is_public: !isPublic.value
    }

    try {
      const response = await $axios.patch(apiUrl, data)

      if (response.status < 200 || response.status >= 300) {
        throw new Error('Network response was not ok. ' + response.statusText);
      }

      isPublic.value = response.data.is_public;
    } catch (error) {
      console.log(error)
    }
  }

</script>

<style scoped>
</style>
