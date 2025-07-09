<template>
  <span v-if="isEditing">
    <input
      v-model="fieldValue"
      :type="inputType"
      class="editable-field"
      v-on:keyup.enter="updateField()"
      v-on:keyup.escape="cancelEdit()"
    />

    <button class="btn btn-sm btn-outline-success ms-1 me-1" title="save" @click="updateField()">
      <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="feather feather-check"><polyline points="20 6 9 17 4 12"></polyline></svg>
    </button>

    <button class="btn btn-sm btn-outline-danger ms-1 me-1" title="cancel" @click="cancelEdit()">
      <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="feather feather-x"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
    </button>
  </span>
  <span v-else>
    <span @click="startEdit">
      {{ displayText }}
      <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="feather feather-edit"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path></svg>
    </span>
  </span>
  <p v-if="errorMessage" class="text-danger" style="font-size: 14pt">{{ errorMessage }}</p>
</template>

<script setup lang="ts">
  import { ref, computed } from 'vue';
  import $axios from '../utils';

  interface Props {
    itemType: string;
    itemId: string;
    itemValue: string;
    fieldName?: string;
    fieldType?: string;
    displayValue?: string;
  }

  const props = defineProps<Props>()

  const isEditing = ref(false);
  const fieldValue = ref(props.itemValue);
  const originalValue = props.itemValue;
  const errorMessage = ref('');

  // Determine input type based on fieldType
  const inputType = computed(() => {
    switch (props.fieldType) {
      case 'date':
        return 'date';
      case 'email':
        return 'email';
      case 'url':
        return 'url';
      case 'number':
        return 'number';
      default:
        return 'text';
    }
  });

  // Display text - use displayValue if provided, otherwise itemValue
  const displayText = computed(() => {
    return props.displayValue || props.itemValue;
  });

  const startEdit = () => {
    isEditing.value = true;
    // Reset to original value when starting edit
    fieldValue.value = props.itemValue;
  };

  const updateField = async () => {
    errorMessage.value = ''

    // Determine field name - default to 'name' for backward compatibility
    const fieldName = props.fieldName || 'name';

    // Use proper CRUD endpoints
    let apiUrl: string;
    const data: Record<string, string | number | boolean | null> = {};
    data[fieldName] = fieldValue.value;

    switch (props.itemType) {
      case 'team':
        apiUrl = `/api/v1/teams/${props.itemId}`;
        break;
      case 'component':
        apiUrl = `/api/v1/components/${props.itemId}`;
        break;
      case 'project':
        apiUrl = `/api/v1/projects/${props.itemId}`;
        break;
      case 'product':
        apiUrl = `/api/v1/products/${props.itemId}`;
        break;
      case 'release':
        apiUrl = `/api/v1/products/${getProductIdFromUrl()}/releases/${props.itemId}`;
        break;
      default:
        errorMessage.value = 'Unknown item type';
        return;
    }

    try {
      const response = await $axios.patch(apiUrl, data);

      if (response.status < 200 || response.status >= 300) {
        throw new Error('Network response was not ok. ' + response.statusText);
      }

      isEditing.value = false;
      // Reload the page to show updated display value (especially for dates)
      window.location.reload();
    } catch (error) {
      fieldValue.value = originalValue;
      errorMessage.value = 'Error updating field. ' + (error as Error).message;
    }
  }

  const cancelEdit = () => {
    isEditing.value = false;
    fieldValue.value = originalValue;
  }

  // Helper function to get product ID from current URL for release endpoints
  const getProductIdFromUrl = (): string => {
    const pathParts = window.location.pathname.split('/');
    const productIndex = pathParts.indexOf('products');
    if (productIndex !== -1 && productIndex + 1 < pathParts.length) {
      return pathParts[productIndex + 1];
    }
    throw new Error('Could not determine product ID from URL');
  }
</script>

<style scoped>
input.editable-field {
  border: none;
  border-bottom: 1px solid #ccc;
  background-color: transparent;
  font-size: 20pt;
}

input.editable-field[type="date"] {
  font-size: 16pt; /* Slightly smaller for date inputs */
  padding: 4px 0;
}
</style>
