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
    // Copy metadata from copyComponentId to props.componentId
    console.log("Copying metadata from " + copyComponentId.value + " to " + props.componentId);

    const apiUrl = '/api/v1/sboms/component/copy-meta';
    interface CopyMetaRequest {
      source_component_id: string;
      target_component_id: string;
    }

    const copyMetaReq: CopyMetaRequest = {
      source_component_id: copyComponentId.value,
      target_component_id: props.componentId
    }

    try {
      const response = await $axios.put(apiUrl, copyMetaReq)

      if (response.status < 200 || response.status >= 300) {
        throw new Error('Network response was not ok. ' + response.statusText);
      }

      // Show success message and refresh the display
      showSuccess('Metadata copied successfully');
      infoComponentKey.value += 1;

    } catch (error) {
      console.log(error)
      if (isAxiosError(error)) {
        showError(`${error.response?.status} - ${error.response?.statusText}: ${error.response?.data?.detail[0].msg}`);
      } else {
        showError('Failed to copy metadata');
      }
    }

    clearCopyComponentMetadata();
  }

</script>

<style scoped>
</style>