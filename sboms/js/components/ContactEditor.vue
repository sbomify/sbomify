<template>
  <div>

    <div class="mb-3">
      <label for="contactName" class="form-label">Contact Name</label>
      <input id="contactName" v-model="contactData.name" type="text" class="form-control" @input="updateModelValue('name')">
    </div>
    <div class="mb-3">
      <label for="contactEmail" class="form-label">Contact Email</label>
      <input id="contactEmail" v-model="contactData.email" type="text" class="form-control" @input="updateModelValue('email')">
    </div>
    <div class="mb-3">
      <label for="contactPhone" class="form-label">Contact Phone</label>
      <input id="contactPhone" v-model="contactData.phone" type="text" class="form-control" @input="updateModelValue('phone')">
    </div>

  </div>

</template>

<script setup lang="ts">
import { ref, watch } from 'vue';
import type { ContactInfo } from '../../../core/js/type_defs.d.ts';


interface Props {
  modelValue: ContactInfo
}

const props = defineProps<Props>()
const emits = defineEmits(['update:modelValue'])

// Define your reactive state
const contactData = ref<ContactInfo>({
  ...props.modelValue
});

// Update contactData if modelValue changes
watch(() => props.modelValue, (newVal) => {
  contactData.value = {
    ...newVal
  };
});


const updateModelValue = (fieldName: keyof ContactInfo) => {
  emits('update:modelValue', {
    ...props.modelValue,
    [fieldName]: contactData.value[fieldName]
  });
};
</script>

<style scoped>
</style>

