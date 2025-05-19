<template>
  <div class="supplier-info-editor">
    <div class="mb-3">
      <label for="supplierName" class="form-label">Name</label>
      <input id="supplierName" v-model="supplierData.name" type="text" class="form-control" @input="updateModelValue('name')">
    </div>
    <div class="mb-3">
      <label for="supplierUrl" class="form-label">URL</label>
      <input id="supplierUrl" v-model="supplierData.url" type="text" class="form-control" @input="updateModelValue('url')">
    </div>
    <div class="mb-3">
      <label for="supplierAddress" class="form-label">Address</label>
      <textarea id="supplierAddress" v-model="supplierData.address" class="form-control" @input="updateModelValue('address')"></textarea>
    </div>


    <h4 class="card-title mb-3">Contacts</h4>
    <ContactsEditor v-model="supplierData.contacts" contact-type="contact" @update:model-value="updateModelValue('contacts')" />

  </div>

</template>

<script setup lang="ts">
import { ref, watch } from 'vue';
import type { SupplierInfo } from '../type_defs.d.ts';
import ContactsEditor from './ContactsEditor.vue';

interface Props {
  modelValue: SupplierInfo;
  validationErrors?: Record<string, string>;
}

const props = defineProps<Props>()
const emits = defineEmits(['update:modelValue'])

// Define your reactive state
const supplierData = ref<SupplierInfo>({
  ...props.modelValue,
});

// TODO: The 'license' field is temporary and will be removed in the future.
// It will be generated ad-hoc from the view for backward compatibility.

watch(() => props.modelValue, (newVal) => {
  console.log('watch -> newVal', newVal);
  supplierData.value = {
    ...newVal
  };
});


const updateModelValue = (fieldName: keyof SupplierInfo) => {
  if (fieldName === 'contacts') {
    emits('update:modelValue', {
      ...props.modelValue,
      contacts: supplierData.value.contacts
    });
  } else {
    emits('update:modelValue', {
      ...props.modelValue,
      [fieldName]: supplierData.value[fieldName]
    });
  }

};
</script>

<style scoped>
/* .supplier-info-editor {
  padding: 20px;
  border: 1px solid #ccc;
  border-radius: 5px;
  margin: 20px 0;
  background-color: #f9f9f9;
  box-shadow: 0 0 10px rgba(0, 0, 0, 0.1);
} */
</style>

