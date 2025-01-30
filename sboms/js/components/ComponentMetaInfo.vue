<template>
  <div class="container-fluid p-0">
    <div v-if="alertMessage.message !== null" role="alert"
      class="alert alert-outline-coloured alert-dismissible"
      :class="'alert-' + alertMessage.alertType">
      <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
      <div class="alert-icon">
        <i class="far fa-fw fa-bell"></i>
      </div>
      <div class="alert-message">
        <strong>{{ alertMessage.title }}</strong> {{ alertMessage.message }}
      </div>
    </div>

    <div class="row">
      <div class="col-12">
        <ComponentMetaInfoDisplay
          v-if="!isEditing"
          :key="infoComponentKey"
          :componentId="props.componentId"
          :showEditButton="allowEdit"
          @edit="isEditing = true"
        />
        <ComponentMetaInfoEditor
          v-else
          :componentId="props.componentId"
          @closeEditor="isEditing=false"
        />
      </div>
    </div>

    <ItemSelectModal
      v-if="selectingCopyComponent"
      v-model="copyComponentId"
      item-type="component"
      :exclude-items="[props.componentId]"
      @canceled="clearCopyComponentMetadata()"
      @selected="copyComponentMetadata()"
    />
  </div>
</template>

<script setup lang="ts">
  // Parent component for toggling between meta info display and edit components.
  import $axios from '../../../core/js/utils';
  import { isAxiosError } from 'axios';
  import { ref } from 'vue';

  import ComponentMetaInfoEditor from './ComponentMetaInfoEditor.vue';
  import ComponentMetaInfoDisplay from './ComponentMetaInfoDisplay.vue';
  import ItemSelectModal from './ItemSelectModal.vue';
  import type { AlertMessage } from '../type_defs.d.ts';

  const props = defineProps(
    {
      componentId: { type: String, required: true },
      allowEdit: { type: Boolean, required: false, default: false },
    }
  )

  const alertMessage = ref<AlertMessage>({
    alertType: null,
    title: null,
    message: null,
  });

  const isEditing = ref(false);
  const selectingCopyComponent = ref(false);
  const copyComponentId = ref("");
  const infoComponentKey = ref(0);  // To force re-render of info component

  const clearCopyComponentMetadata = () => {
    selectingCopyComponent.value = false;
    copyComponentId.value = "";
  }

  const copyComponentMetadata = async () => {
    // Copy metadata from copyComponentId to props.componentId
    console.log("Copying metadata from " + copyComponentId.value + " to " + props.componentId);

    // clear alert message
    alertMessage.value = {
      alertType: null,
      title: null,
      message: null,
    };

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

      alertMessage.value = {
        alertType: 'success',
        title: 'Success',
        message: 'Metadata copied successfully'
      }

      // force re-render of info component
      infoComponentKey.value += 1;

    } catch (error) {
      console.log(error)
      if (isAxiosError(error)) {
        alertMessage.value = {
          alertType: 'danger',
          title: `${error.response?.status} - ${error.response?.statusText}`,
          message: error.response?.data?.detail[0].msg
        }

      } else {
        alertMessage.value = {
          alertType: 'danger',
          title: 'Error',
          message: 'Failed to save metadata'
        }
      }
    }

    clearCopyComponentMetadata();
  }

</script>

<style scoped>
</style>