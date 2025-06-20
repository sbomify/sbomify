<template>
  <div class="supplier-info-editor">
    <div class="mb-3">
      <label for="supplierName" class="form-label">Name</label>
      <input id="supplierName" v-model="supplierData.name" type="text" class="form-control" @input="updateModelValue('name')">
    </div>

    <div class="mb-3">
      <label class="form-label">URLs</label>
      <div v-if="supplierData.url && supplierData.url.length > 0" class="url-list">
        <div v-for="(url, index) in supplierData.url" :key="index" class="input-group mb-2">
          <input
            :value="url"
            type="url"
            class="form-control"
            placeholder="https://example.com"
            @input="(event) => {
              if (supplierData.url) {
                supplierData.url[index] = (event.target as HTMLInputElement).value;
                updateModelValue('url');
              }
            }"
          >
                    <button
            type="button"
            class="btn btn-outline-danger"
            :disabled="supplierData.url.length <= 1"
            @click="removeUrl(index)"
          >
            <i class="fa-solid fa-times"></i>
          </button>
        </div>
      </div>
      <div v-else class="mb-2">
        <div class="input-group">
                              <input
            v-model="newUrlInput"
            type="url"
            class="form-control"
            placeholder="https://example.com"
            @keyup.enter="addUrlFromPlaceholder"
          >
          <button
            type="button"
            class="btn btn-outline-primary"
            @click="addUrlFromPlaceholder"
          >
            <i class="fa-solid fa-plus"></i>
          </button>
        </div>
      </div>
      <button
        v-if="supplierData.url && supplierData.url.length > 0"
        type="button"
        class="btn btn-sm btn-outline-primary"
        @click="addUrl"
      >
        <i class="fa-solid fa-plus me-1"></i>Add Another URL
      </button>
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

const newUrlInput = ref<string>('');

watch(() => props.modelValue, (newVal) => {
  console.log('watch -> newVal', newVal);
  supplierData.value = {
    ...newVal
  };
  // Ensure url is always an array
  if (typeof supplierData.value.url === 'string') {
    supplierData.value.url = [supplierData.value.url];
  } else if (!supplierData.value.url) {
    supplierData.value.url = [];
  }
});

// Initialize url as empty array if needed
if (typeof supplierData.value.url === 'string') {
  supplierData.value.url = [supplierData.value.url];
} else if (!supplierData.value.url) {
  supplierData.value.url = [];
}

const addUrl = () => {
  if (!supplierData.value.url) {
    supplierData.value.url = [];
  }
  supplierData.value.url.push('');
  updateModelValue('url');
};

const addUrlFromPlaceholder = () => {
  if (newUrlInput.value.trim()) {
    if (!supplierData.value.url) {
      supplierData.value.url = [];
    }
    supplierData.value.url.push(newUrlInput.value.trim());
    newUrlInput.value = '';
    updateModelValue('url');
  }
};

const removeUrl = (index: number) => {
  if (supplierData.value.url && supplierData.value.url.length > 1) {
    supplierData.value.url.splice(index, 1);
    updateModelValue('url');
  }
};

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
.url-list {
  max-height: 200px;
  overflow-y: auto;
}

.input-group .btn {
  border-radius: 0 6px 6px 0;
}

.input-group .form-control {
  border-radius: 6px 0 0 6px;
}

.btn-sm {
  font-size: 0.875rem;
  padding: 0.375rem 0.75rem;
}

.fa-solid {
  font-size: 0.875rem;
}
</style>

