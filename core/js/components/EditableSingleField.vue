<template>
  <span v-if="isEditing">
    <input v-model="fieldValue" type="text" class="editable-field" v-on:keyup.enter="updateField()" v-on:keyup.escape="cancelEdit()" />

    <button class="btn btn-sm btn-outline-success ms-1 me-1" title="save" @click="updateField()">
      <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="feather feather-check"><polyline points="20 6 9 17 4 12"></polyline></svg>
    </button>

    <button class="btn btn-sm btn-outline-danger ms-1 me-1" title="cancel" @click="cancelEdit()">
      <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="feather feather-x"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
    </button>
  </span>
  <span v-else>
    <span @click="isEditing = true">
      {{ fieldValue }}
      <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="feather feather-edit"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path></svg>
    </span>
  </span>
  <p v-if="errorMessage" class="text-danger" style="font-size: 14pt">{{ errorMessage }}</p>
</template>

<script setup lang="ts">
  import { ref } from 'vue';
  import $axios from '../utils';

  interface Props {
    itemType: string;
    itemId: string;
    itemValue: string;
  }

  const props = defineProps<Props>()

  const isEditing = ref(false);
  const fieldValue = ref(props.itemValue);
  const oldValue = fieldValue.value;
  const errorMessage = ref('');



    const updateField = async () => {
    errorMessage.value = ''

    const apiUrl = '/api/v1/rename/' + props.itemType + '/' + props.itemId;
    const data = {
      name: fieldValue.value
    }

    try {
      const response = await $axios.patch(apiUrl, data)

      if (response.status < 200 || response.status >= 300) {
        throw new Error('Network response was not ok. ' + response.statusText);
      }

      isEditing.value = false;
    } catch (error) {
      fieldValue.value = oldValue;
      errorMessage.value = 'Error updating field. ' + (error as Error).message;
    }
  }

  const cancelEdit = () => {
    isEditing.value = false;
    fieldValue.value = oldValue;
  }
</script>

<style scoped>
input.editable-field {
  border: none;
  border-bottom: 1px solid #ccc;
  background-color: transparent;
  font-size: 20pt;
}
</style>
