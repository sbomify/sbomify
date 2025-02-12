<template>
  <div class="card">
    <div class="card-body">
      <h4 class="d-flex justify-content-between align-items-center mb-4" style="cursor: pointer;" @click="toggleExpand">
        Component Metadata
        <div class="d-flex gap-2 align-items-center">
          <button class="btn btn-outline-secondary btn-sm" @click.stop="$emit('closeEditor')">
            <i class="fa-solid fa-xmark"></i>
          </button>
          <svg v-if="!isExpanded" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"></polyline></svg>
          <svg v-if="isExpanded" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"></polyline></svg>
        </div>
      </h4>

      <div v-if="isExpanded">
        <div class="container-fluid p-0">
          <div class="row">
            <div class="col-sm-12 col-lg-6">
              <div class="card">
                <div class="card-header">
                  <h4 class="card-title">
                    Supplier Information
                    <i class="fa-regular fa-circle-question help-icon">
                      <span class="tooltiptext">Organization that supplied or manufactured the component</span>
                    </i>
                  </h4>
                </div>
                <div class="card-body">
                  <SupplierEditor
                    v-model="metadata.supplier"
                    :validation-errors="validationErrors.supplier"
                    @update:modelValue="validateSupplier"
                  />
                </div>
              </div>
            </div>

            <div class="col-12 col-lg-6">
              <div class="card">
                <div class="card-header">
                  <h4 class="card-title">
                    Lifecycle Phase
                    <i class="fa-regular fa-circle-question help-icon">
                      <span class="tooltiptext">Current phase in the component's lifecycle</span>
                    </i>
                  </h4>
                </div>
                <div class="card-body">
                  <div class="form-group">
                    <select
                      v-model="metadata.lifecycle_phase"
                      class="form-select"
                      :class="{ 'is-invalid': validationErrors.lifecycle_phase }"
                    >
                      <option value="">Select a phase...</option>
                      <option
                        v-for="phase in orderedLifecyclePhases"
                        :key="phase.value"
                        :value="phase.value"
                      >
                        {{ phase.label }}
                      </option>
                    </select>
                    <div v-if="validationErrors.lifecycle_phase" class="invalid-feedback">
                      {{ validationErrors.lifecycle_phase }}
                    </div>
                  </div>
                </div>
              </div>

              <div class="card">
                <div class="card-header">
                  <h4 class="card-title">
                    Licenses
                    <i class="fa-regular fa-circle-question help-icon">
                      <span class="tooltiptext">Software licenses that apply to this component</span>
                    </i>
                  </h4>
                </div>
                <div class="card-body">
                  <LicensesEditor
                    v-model="metadata.licenses"
                    :validation-errors="validationErrors.licenses"
                    @update:modelValue="validateLicenses"
                  />
                </div>
              </div>

              <div class="card">
                <div class="card-header">
                  <h4 class="card-title">
                    Authors
                    <i class="fa-regular fa-circle-question help-icon">
                      <span class="tooltiptext">People who contributed to this component</span>
                    </i>
                  </h4>
                </div>
                <div class="card-body">
                  <ContactsEditor
                    v-model="metadata.authors"
                    contact-type="author"
                    :validation-errors="validationErrors.authors"
                    @update:modelValue="validateAuthors"
                  />
                </div>
              </div>
            </div>
          </div>

          <div class="row mb-4">
            <div class="col-12 col-lg-6 d-grid">
              <button class="btn btn-secondary" @click="handleCancel">Cancel</button>
            </div>
            <div class="col-12 col-lg-6 d-grid">
              <button
                class="btn btn-primary"
                :disabled="!isFormValid || isSaving"
                @click="updateMetaData"
              >
                <span v-if="isSaving">
                  <i class="fa-solid fa-spinner fa-spin me-2"></i>Saving...
                </span>
                <span v-else>Save Changes</span>
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
  import $axios from '../../../core/js/utils';
  import { isAxiosError } from 'axios';
  import { ref, computed, onMounted, onBeforeUnmount } from 'vue';
  import type { ComponentMetaInfo, SupplierInfo, ContactInfo, CustomLicense, AlertMessage } from '../type_defs.d.ts';
  import SupplierEditor from './SupplierEditor.vue';
  import LicensesEditor from './LicensesEditor.vue';
  import ContactsEditor from './ContactsEditor.vue';
  import { showSuccess, showError } from '../../../core/js/alerts';

  interface Props {
    componentId: string;
  }

  const emits = defineEmits(['closeEditor'])
  const props = defineProps<Props>()

  const LIFECYCLE_ORDER = [
    "design",
    "pre-build",
    "build",
    "post-build",
    "operations",
    "discovery",
    "decommission"
  ];

  const formatLifecyclePhase = (phase: string): string => {
    // Special case for pre/post-build to keep the hyphen
    if (phase === 'pre-build') return 'Pre-Build';
    if (phase === 'post-build') return 'Post-Build';

    // Regular title case for other phases
    return phase.charAt(0).toUpperCase() + phase.slice(1);
  };

  const orderedLifecyclePhases = computed(() => {
    return LIFECYCLE_ORDER.map(phase => ({
      value: phase,
      label: formatLifecyclePhase(phase)
    }));
  });

  const metadata = ref<ComponentMetaInfo>({
    supplier: {
      name: null,
      url: null,
      address: null,
      contacts: []
    } as SupplierInfo,
    authors: [],
    licenses: [],
    lifecycle_phase: null
  });

  const alertMessage = ref<AlertMessage>({
    alertType: null,
    title: null,
    message: null,
  });

  const validationErrors = ref({
    supplier: {} as Record<string, string>,
    authors: {} as Record<string, string>,
    licenses: {} as Record<string, string>,
    lifecycle_phase: null as string | null
  });

  const isSaving = ref(false);
  const hasUnsavedChanges = ref(false);
  const originalMetadata = ref<string | null>(null);

  const isFormValid = computed(() => {
    // Only check for actual validation errors
    const hasSupplierErrors = Object.keys(validationErrors.value.supplier).length > 0;
    const hasAuthorErrors = Object.keys(validationErrors.value.authors).length > 0;
    const hasLicenseErrors = Object.keys(validationErrors.value.licenses).length > 0;
    const hasLifecycleErrors = validationErrors.value.lifecycle_phase !== null;

    return !hasSupplierErrors && !hasAuthorErrors && !hasLicenseErrors && !hasLifecycleErrors;
  });

  const validateSupplier = (supplier: SupplierInfo) => {
    const errors: Record<string, string> = {};

    // Only validate URL if it's provided
    if (supplier.url && !isValidUrl(supplier.url)) {
      errors.url = 'Please enter a valid URL';
    }

    validationErrors.value.supplier = errors;
    hasUnsavedChanges.value = true;
  };

  const validateAuthors = (authors: ContactInfo[]): void => {
    const errors: Record<string, string> = {};

    authors.forEach((author, index) => {
      if (author.email && !isValidEmail(author.email)) {
        errors[`email${index}`] = 'Please enter a valid email';
      }
    });

    validationErrors.value.authors = errors;
    hasUnsavedChanges.value = true;
  };

  const validateLicenses = (licenses: (string | CustomLicense)[]): void => {
    const errors: Record<string, string> = {};

    licenses.forEach((license, index) => {
      if (typeof license === 'object' && license.name === '') {
        errors[`license${index}`] = 'License name is required when adding a custom license';
      }
    });

    validationErrors.value.licenses = errors;
    hasUnsavedChanges.value = true;
  };

  const isValidEmail = (email: string): boolean => {
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    return emailRegex.test(email);
  };

  const isValidUrl = (url: string): boolean => {
    try {
      new URL(url);
      return true;
    } catch {
      return false;
    }
  };

  // Add beforeunload event handler
  const handleBeforeUnload = (e: BeforeUnloadEvent) => {
    if (hasUnsavedChanges.value) {
      e.preventDefault();
      e.returnValue = '';
    }
  };

  onMounted(async () => {
    alertMessage.value = {
      alertType: null,
      title: null,
      message: null,
    };

    try {
      const response = await $axios.get(`/api/v1/sboms/component/${props.componentId}/meta`);
      if (response.status < 200 || response.status >= 300) {
        throw new Error('Network response was not ok. ' + response.statusText);
      }
      metadata.value = {...metadata.value, ...response.data};
      originalMetadata.value = JSON.stringify(metadata.value);

      // Validate initial data
      validateSupplier(metadata.value.supplier);
      validateAuthors(metadata.value.authors);
      validateLicenses(metadata.value.licenses);

      // Add beforeunload listener
      window.addEventListener('beforeunload', handleBeforeUnload);
    } catch (error) {
      console.error(error);
      alertMessage.value = {
        alertType: 'danger',
        title: 'Error',
        message: 'Failed to load metadata'
      };
    }
  });

  onBeforeUnmount(() => {
    window.removeEventListener('beforeunload', handleBeforeUnload);
  });

  const handleCancel = () => {
    if (hasUnsavedChanges.value) {
      if (confirm('You have unsaved changes. Are you sure you want to leave?')) {
        emits('closeEditor');
      }
    } else {
      emits('closeEditor');
    }
  };

  const updateMetaData = async () => {
    // Only validate what's provided
    if (metadata.value.supplier.url) {
      validateSupplier(metadata.value.supplier);
    }
    if (metadata.value.authors.length > 0) {
      validateAuthors(metadata.value.authors);
    }
    if (metadata.value.licenses.length > 0) {
      validateLicenses(metadata.value.licenses);
    }

    if (!isFormValid.value) {
      alertMessage.value = {
        alertType: 'danger',
        title: 'Validation Error',
        message: 'Please fix the validation errors before saving'
      };
      return;
    }

    isSaving.value = true;
    alertMessage.value = {
      alertType: null,
      title: null,
      message: null,
    };

    try {
      const response = await $axios.put(`/api/v1/sboms/component/${props.componentId}/meta`, metadata.value)

      if (response.status < 200 || response.status >= 300) {
        throw new Error('Network response was not ok. ' + response.statusText);
      }

      hasUnsavedChanges.value = false;
      await showSuccess('Changes saved successfully');

      // Switch to display view after delay
      setTimeout(() => {
        emits('closeEditor');
      }, 1500);

    } catch (error) {
      console.error(error);
      if (isAxiosError(error)) {
        showError(`${error.response?.status} - ${error.response?.statusText}: ${error.response?.data?.detail[0].msg}`);
      } else {
        showError('Failed to save metadata');
      }
    } finally {
      isSaving.value = false;
    }
  }

  // Add isExpanded state
  const isExpanded = ref(true);

  // Add toggle function
  const toggleExpand = () => {
    isExpanded.value = !isExpanded.value;
  };
</script>

<style scoped>
.form-group {
  margin-bottom: 1.5rem;
}

.form-label {
  font-weight: 500;
  color: #495057;
  margin-bottom: 0.5rem;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.help-icon {
  color: #6c757d;
  cursor: help;
  font-size: 0.875rem;
  position: relative;
  margin-left: 0.5rem;
}

.help-icon .tooltiptext {
  visibility: hidden;
  width: 200px;
  background-color: #2c3e50;
  color: #fff;
  text-align: center;
  border-radius: 6px;
  padding: 8px;
  position: absolute;
  z-index: 1;
  bottom: 125%;
  left: 50%;
  transform: translateX(-50%);
  opacity: 0;
  transition: opacity 0.2s;
  font-size: 0.875rem;
  font-weight: normal;
  text-transform: none;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  line-height: 1.5;
  letter-spacing: normal;
}

.help-icon:hover .tooltiptext {
  visibility: visible;
  opacity: 1;
}

.form-control, .form-select {
  border-color: #dee2e6;
  padding: 0.75rem;
  border-radius: 6px;
  transition: all 0.2s ease;
}

.form-control:focus, .form-select:focus {
  border-color: #80bdff;
  box-shadow: 0 0 0 0.2rem rgba(0,123,255,0.15);
}

.form-control.is-invalid, .form-select.is-invalid {
  border-color: #dc3545;
  background-image: url("data:image/svg+xml,%3csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' fill='none' stroke='%23dc3545' viewBox='0 0 12 12'%3e%3ccircle cx='6' cy='6' r='4.5'/%3e%3cpath stroke-linejoin='round' d='M5.8 3.6h.4L6 6.5z'/%3e%3ccircle cx='6' cy='8.2' r='.6' fill='%23dc3545' stroke='none'/%3e%3c/svg%3e");
  background-repeat: no-repeat;
  background-position: right calc(0.375em + 0.1875rem) center;
  background-size: calc(0.75em + 0.375rem) calc(0.75em + 0.375rem);
}

.invalid-feedback {
  display: block;
  color: #dc3545;
  font-size: 0.875rem;
  margin-top: 0.25rem;
}

.card {
  border: 1px solid #dee2e6;
  border-radius: 0.5rem;
  margin-bottom: 1rem;
}

.card-header {
  background: #f8f9fa;
  border-bottom: 1px solid #eaecef;
  padding: 1.25rem;
  border-radius: 8px 8px 0 0;
}

.card-body {
  padding: 1.25rem;
}

.card-title {
  color: #2c3e50;
  font-size: 1.1rem;
  font-weight: 600;
  margin: 0;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
</style>

