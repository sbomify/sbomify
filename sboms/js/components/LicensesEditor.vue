<template>

  <div v-if="modelValue.length > 0" class="licenses-list">
    <div v-for="(license, licenseIndex) in modelValue" class="license-badge">
      <span v-if="typeof license === 'string'">{{ license }}</span>
      <span v-else-if="license && license.name">{{ license.name }} (custom)</span>
      <i class="far fa-times-circle" @click="removeLicense(licenseIndex)"></i>
    </div>
  </div>

  <div class="license-type-selector">
    <div
      class="license-type-option"
      :class="{ active: licenseType === 'well-known' }"
      @click="licenseType = 'well-known'"
    >
      <i class="far fa-check-circle"></i>
      Well-known
    </div>
    <div
      class="license-type-option"
      :class="{ active: licenseType === 'custom' }"
      @click="licenseType = 'custom'"
    >
      <i class="far fa-edit"></i>
      Custom
    </div>
  </div>

  <div v-if="licenseType === 'well-known'" class="well-known-license-selector">
    <select
      v-model="selectedLicense"
      class="form-select"
      @change="addSelectedLicense"
    >
      <option value="">Select a license...</option>
      <optgroup label="Common Licenses">
        <option value="MIT">MIT License</option>
        <option value="Apache-2.0">Apache License 2.0</option>
        <option value="GPL-3.0">GNU General Public License v3.0</option>
        <option value="BSD-3-Clause">BSD 3-Clause License</option>
        <option value="ISC">ISC License</option>
      </optgroup>
      <optgroup label="All Licenses">
        <option v-for="license in remainingLicenses" :value="license">{{ license }}</option>
      </optgroup>
    </select>
  </div>

  <div v-if="licenseType === 'custom'" class="custom-license-editor">
    <div class="form-group">
      <label class="form-label">Name <span class="text-danger">*</span></label>
      <input
        v-model="customLicenseData.name"
        type="text"
        class="form-control"
        :class="{ 'is-invalid': validationErrors?.name }"
        placeholder="Enter license name"
      >
      <div v-if="validationErrors?.name" class="invalid-feedback">
        {{ validationErrors.name }}
      </div>
    </div>

    <div class="form-group">
      <label class="form-label">URL</label>
      <input
        v-model="customLicenseData.url"
        type="url"
        class="form-control"
        :class="{ 'is-invalid': validationErrors?.url }"
        placeholder="https://example.com/license"
      >
      <div v-if="validationErrors?.url" class="invalid-feedback">
        {{ validationErrors.url }}
      </div>
    </div>

    <div class="form-group mb-0">
      <label class="form-label">License Text</label>
      <textarea
        v-model="customLicenseData.text"
        class="form-control"
        :class="{ 'is-invalid': validationErrors?.text }"
        rows="4"
        placeholder="Enter the full text of the license"
      ></textarea>
      <div v-if="validationErrors?.text" class="invalid-feedback">
        {{ validationErrors.text }}
      </div>
    </div>

    <button
      class="btn-add mt-3"
      :disabled="!customLicenseData.name"
      @click="addCustomLicense"
    >
      <i class="far fa-plus-circle"></i>
      Add Custom License
    </button>
  </div>
</template>

<script setup lang="ts">
  import { ref, computed } from 'vue';
  import { License } from '../enums';
  import type { CustomLicense } from '../type_defs';

  interface Props {
    modelValue: (string | CustomLicense)[];
    validationErrors?: Record<string, string>;
  }

  const props = defineProps<Props>()
  const emits = defineEmits(['update:modelValue'])

  const selectedLicense = ref<string>('');
  const licenseType = ref<string>('well-known');
  const customLicenseData = ref<CustomLicense>({
    name: null,
    url: null,
    text: null
  });

  // DEPRECATED: The 'license' field is deprecated and will be removed. Do not use in new code. Only here for backward compatibility.

  // Common licenses to show at the top
  const commonLicenses = ['MIT', 'Apache-2.0', 'GPL-3.0', 'BSD-3-Clause', 'ISC'];

  // Compute remaining licenses excluding the common ones
  const remainingLicenses = computed(() => {
    return Object.values(License).filter(license => !commonLicenses.includes(license));
  });

  const addSelectedLicense = () => {
    if (!selectedLicense.value) return;

    // Check if license is already added
    if (!props.modelValue.includes(selectedLicense.value)) {
      emits('update:modelValue', [...props.modelValue, selectedLicense.value]);
    }

    // Reset selection
    selectedLicense.value = '';
  };

  const addCustomLicense = () => {
    if (!customLicenseData.value.name?.trim()) return;

    emits('update:modelValue', [...props.modelValue, { ...customLicenseData.value }]);
    customLicenseData.value = { name: null, url: null, text: null };
  };

  const removeLicense = (licenseIndex: number) => {
    const newLicenses = [...props.modelValue];
    newLicenses.splice(licenseIndex, 1);
    emits('update:modelValue', newLicenses);
  };

</script>

<style scoped>

  .licenses-list {
    display: flex;
    flex-wrap: wrap;
    gap: 0.75rem;
    margin-bottom: 1.5rem;
  }

  .license-badge {
    background-color: #ffffff;
    border: 1px solid #dee2e6;
    border-radius: 6px;
    padding: 0.75rem 1rem;
    display: inline-flex;
    align-items: center;
    gap: 0.75rem;
    box-shadow: 0 1px 2px rgba(0,0,0,0.05);
    transition: all 0.2s ease;
  }

  .license-badge:hover {
    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    transform: translateY(-1px);
  }

  .license-badge i {
    cursor: pointer;
    color: #6c757d;
    transition: all 0.2s ease;
    font-size: 0.875rem;
  }

  .license-badge i:hover {
    color: #dc3545;
    transform: scale(1.1);
  }

  .license-type-selector {
    display: flex;
    gap: 1rem;
    margin-bottom: 1.5rem;
    padding: 0.5rem;
    background: #f8f9fa;
    border-radius: 6px;
  }

  .license-type-option {
    flex: 1;
    text-align: center;
    padding: 0.75rem;
    border-radius: 4px;
    cursor: pointer;
    transition: all 0.2s ease;
    border: 1px solid transparent;
  }

  .license-type-option:hover {
    background: #ffffff;
  }

  .license-type-option.active {
    background: #ffffff;
    border-color: #0d6efd;
    color: #0d6efd;
    box-shadow: 0 1px 3px rgba(13,110,253,0.1);
  }

  .license-type-option i {
    margin-right: 0.5rem;
  }

  .well-known-license-selector {
    margin-bottom: 1rem;
  }

  .form-select {
    width: 100%;
    padding: 0.75rem;
    border: 1px solid #dee2e6;
    border-radius: 6px;
    color: #495057;
    cursor: pointer;
    transition: all 0.2s ease;
  }

  .form-select:focus {
    border-color: #80bdff;
    box-shadow: 0 0 0 0.2rem rgba(0,123,255,0.15);
  }

  optgroup {
    font-weight: 600;
    color: #2c3e50;
  }

  option {
    padding: 0.5rem;
  }

  .custom-license-editor {
    background: #ffffff;
    border: 1px solid #dee2e6;
    border-radius: 6px;
    padding: 1.5rem;
  }

  .form-group {
    margin-bottom: 1.25rem;
  }

  .form-label {
    font-weight: 500;
    color: #495057;
    margin-bottom: 0.5rem;
    display: block;
  }

  .form-control {
    width: 100%;
    padding: 0.75rem;
    border: 1px solid #dee2e6;
    border-radius: 6px;
    transition: all 0.2s ease;
  }

  .form-control:focus {
    border-color: #80bdff;
    box-shadow: 0 0 0 0.2rem rgba(0,123,255,0.15);
  }

  .btn-add {
    width: 100%;
    padding: 0.75rem;
    background: #f8f9fa;
    border: 1px dashed #dee2e6;
    border-radius: 6px;
    color: #6c757d;
    transition: all 0.2s ease;
    cursor: pointer;
  }

  .btn-add:hover:not(:disabled) {
    background: #ffffff;
    border-color: #0d6efd;
    color: #0d6efd;
  }

  .btn-add:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }

  .btn-add i {
    margin-right: 0.5rem;
  }

  .validation-error {
    color: #dc3545;
    font-size: 0.875rem;
    margin-top: 0.5rem;
  }
</style>
