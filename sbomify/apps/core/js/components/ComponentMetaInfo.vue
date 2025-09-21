<template>
  <ComponentMetaInfoDisplay
    v-if="!isEditing"
    :key="infoComponentKey"
    :componentId="props.componentId"
    :showEditButton="allowEdit"
    @edit="isEditing = true"
    @copy="selectingCopyComponent = true"
  />
  <ComponentMetaInfoEditor
    v-else
    :componentId="props.componentId"
    @closeEditor="isEditing=false"
  />

  <ItemSelectModal
    v-if="selectingCopyComponent"
    v-model="copyComponentId"
    item-type="component"
    :exclude-items="[props.componentId]"
    @canceled="clearCopyComponentMetadata()"
    @selected="copyComponentMetadata()"
  />
</template>

<script setup lang="ts">
  // Parent component for toggling between meta info display and edit components.
  import $axios from '../../../core/js/utils';
  import { isAxiosError } from 'axios';
  import { ref } from 'vue';

  import ComponentMetaInfoEditor from './ComponentMetaInfoEditor.vue';
  import ComponentMetaInfoDisplay from './ComponentMetaInfoDisplay.vue';
  import ItemSelectModal from './ItemSelectModal.vue';
  import { showSuccess, showError } from '../../../core/js/alerts';

  interface Props {
    componentId: string;
    allowEdit?: boolean;
  }

  const props = defineProps<Props>();
  const isEditing = ref(false);
  const selectingCopyComponent = ref(false);
  const copyComponentId = ref("");
  const infoComponentKey = ref(0);  // To force re-render of info component

  const clearCopyComponentMetadata = () => {
    selectingCopyComponent.value = false;
    copyComponentId.value = "";
  };

  const copyComponentMetadata = async () => {
    // Copy metadata from copyComponentId to props.componentId using GET + PATCH
    console.log("Copying metadata from " + copyComponentId.value + " to " + props.componentId);

    try {
      // First, get metadata from source component
      const sourceResponse = await $axios.get(`/api/v1/components/${copyComponentId.value}/metadata`);

      if (sourceResponse.status < 200 || sourceResponse.status >= 300) {
        throw new Error('Failed to get source metadata. ' + sourceResponse.statusText);
      }

      const sourceMetadata = sourceResponse.data;

      // Remove component-specific fields (id, name) that shouldn't be copied
      const { id, name, ...metadataToCopy } = sourceMetadata;
      void id; void name;  // Mark as intentionally unused

      // Then, patch the target component with the copied metadata
      const targetResponse = await $axios.patch(`/api/v1/components/${props.componentId}/metadata`, metadataToCopy);

      if (targetResponse.status < 200 || targetResponse.status >= 300) {
        throw new Error('Failed to update target metadata. ' + targetResponse.statusText);
      }

      // Show success message and refresh the display
      showSuccess('Metadata copied successfully');
      infoComponentKey.value += 1;

    } catch (error) {
      console.log(error)
      if (isAxiosError(error)) {
        showError(`${error.response?.status} - ${error.response?.statusText}: ${error.response?.data?.detail}`);
      } else {
        showError('Failed to copy metadata');
      }
    }

    clearCopyComponentMetadata();
  }

</script>

<style scoped>
</style>