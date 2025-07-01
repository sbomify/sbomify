<template>
  <StandardCard
    title="Component Metadata"
    variant="settings"
    size="large"
    shadow="md"
  >
    <template #info-notice>
      <strong>Augmentation:</strong> Enable the <a href="#" class="text-decoration-none" style="color: #4f46e5;">Augmentation</a> feature to include this metadata in your SBOM
    </template>

      <div>
        <div class="container-fluid p-0">
          <div class="row">
            <div class="col-sm-12 col-lg-6">
              <StandardCard
                variant="settings"
                shadow="sm"
              >
                <template #title>
                  Supplier Information
                  <i class="fa-regular fa-circle-question help-icon">
                    <span class="tooltiptext">Organization that supplied or manufactured the component</span>
                  </i>
                </template>

                <SupplierEditor
                  v-model="metadata.supplier"
                  :validation-errors="validationErrors.supplier"
                  @update:modelValue="validateSupplier"
                />
              </StandardCard>
            </div>

            <div class="col-12 col-lg-6">
              <StandardCard
                variant="settings"
                shadow="sm"
              >
                <template #title>
                  Lifecycle Phase
                  <i class="fa-regular fa-circle-question help-icon">
                    <span class="tooltiptext">Current phase in the component's lifecycle</span>
                  </i>
                </template>

                <div class="form-group">
                  <select
                    v-model="metadata.lifecycle_phase"
                    class="form-select"
                    :class="{ 'is-invalid': validationErrors.lifecycle_phase }"
                  >
                    <option :value="null">Select a phase...</option>
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
              </StandardCard>

              <StandardCard
                variant="settings"
                shadow="sm"
              >
                <template #title>
                  Licenses
                  <i class="fa-regular fa-circle-question help-icon">
                    <span class="tooltiptext">Software licenses that apply to this component</span>
                  </i>
                </template>

                <LicensesEditor
                  v-model="metadata.licenses"
                  :validation-errors="validationErrors.licenses"
                  :validationResponse="{ status: 200, unknown_tokens: [] }"
                  @update:modelValue="validateLicenses"
                />
              </StandardCard>

              <StandardCard
                variant="settings"
                shadow="sm"
              >
                <template #title>
                  Authors
                  <i class="fa-regular fa-circle-question help-icon">
                    <span class="tooltiptext">People who contributed to this component</span>
                  </i>
                </template>

                <ContactsEditor
                  v-model="metadata.authors"
                  contact-type="author"
                  :validation-errors="validationErrors.authors"
                  @update:modelValue="validateAuthors"
                />
              </StandardCard>
            </div>
          </div>

          <div class="actions-section mt-4 pt-4 border-top">
            <div class="row g-3">
              <div class="col-12 col-lg-4">
                <button class="btn btn-outline-secondary btn-lg w-100" @click="handleCancel">
                  <i class="fa-solid fa-times me-2"></i>
                  Cancel Changes
                </button>
              </div>
              <div class="col-12 col-lg-8">
                <button
                  class="btn btn-success btn-lg w-100"
                  :disabled="!isFormValid || isSaving"
                  @click="updateMetaData"
                >
                  <span v-if="isSaving">
                    <i class="fa-solid fa-spinner fa-spin me-2"></i>Saving Changes...
                  </span>
                  <span v-else>
                    <i class="fa-solid fa-save me-2"></i>Save Component Metadata
                  </span>
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
  </StandardCard>
</template>

<script setup lang="ts">
  import $axios from '../../../core/js/utils';
  import { isAxiosError } from 'axios';
  import { ref, computed, onMounted, onBeforeUnmount } from 'vue';
  import type { ComponentMetaInfo, SupplierInfo, ContactInfo, CustomLicense, AlertMessage } from '../type_defs.d.ts';
  import SupplierEditor from './SupplierEditor.vue';
  import LicensesEditor from './LicensesEditor.vue';
  import ContactsEditor from './ContactsEditor.vue';
  import StandardCard from '../../../core/js/components/StandardCard.vue';
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
    id: '',
    name: '',
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

    // Validate URLs if provided (now supporting arrays)
    if (supplier.url && Array.isArray(supplier.url)) {
      supplier.url.forEach((url, index) => {
        if (url && !isValidUrl(url)) {
          errors[`url${index}`] = `URL ${index + 1}: Please enter a valid URL`;
        }
      });
    } else if (supplier.url && typeof supplier.url === 'string' && !isValidUrl(supplier.url)) {
      // Handle legacy string format for backward compatibility
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

  interface LicenseApiResponse {
    key: string;
    known?: boolean;
  }

  const validateLicenses = (licenses: (string | CustomLicense)[]): void => {
    // Deduplicate licenses: for strings, by value; for objects, by .name or .key
    const seen = new Set<string>();
    const deduped: (string | CustomLicense)[] = [];
    licenses.forEach(lic => {
      let key: string;
      let itemToAdd: string | CustomLicense;

      if (typeof lic === 'string') {
        key = lic;
        itemToAdd = lic;
      } else if (lic.name) {
        key = lic.name;  // CustomLicense format
        itemToAdd = lic;
      } else if ('key' in lic && typeof lic.key === 'string') {
        const apiResponse = lic as LicenseApiResponse;
        key = apiResponse.key;  // API response format { key: "Apache-2.0", known: true }
        itemToAdd = key;  // Convert API format to string for consistency
      } else {
        key = '';  // fallback
        itemToAdd = lic;
      }

      if (key && !seen.has(key)) {
        seen.add(key);
        deduped.push(itemToAdd);
      }
    });

    // Replace the licenses array with deduped version
    metadata.value.licenses = deduped;

    const errors: Record<string, string> = {};
    deduped.forEach((license, index) => {
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
      const response = await $axios.get(`/api/v1/components/${props.componentId}/metadata`);
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
    // Only validate what's provided - validation function handles both string and array cases
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
      // Only send changed fields in PATCH request
      const currentMetadata = JSON.stringify(metadata.value);
      const original = JSON.parse(originalMetadata.value || '{}');
      const current = JSON.parse(currentMetadata);

      const updatePayload: Partial<ComponentMetaInfo> = {};

      // Check each field for changes (excluding read-only fields id and name)
      if (JSON.stringify(current.supplier) !== JSON.stringify(original.supplier)) {
        updatePayload.supplier = current.supplier;
      }
      if (JSON.stringify(current.authors) !== JSON.stringify(original.authors)) {
        updatePayload.authors = current.authors;
      }
      if (JSON.stringify(current.licenses) !== JSON.stringify(original.licenses)) {
        updatePayload.licenses = current.licenses;
      }
      if (current.lifecycle_phase !== original.lifecycle_phase) {
        updatePayload.lifecycle_phase = current.lifecycle_phase;
      }

      // Only make the request if there are actually changes
      if (Object.keys(updatePayload).length === 0) {
        showSuccess('No changes to save');
        emits('closeEditor');
        return;
      }

      const response = await $axios.patch(`/api/v1/components/${props.componentId}/metadata`, updatePayload)

      if (response.status < 200 || response.status >= 300) {
        throw new Error('Network response was not ok. ' + response.statusText);
      }

      hasUnsavedChanges.value = false;
      showSuccess('Changes saved successfully');

      // Navigate back immediately after saving
      emits('closeEditor');

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

  // Component is always expanded now - no collapsible functionality needed
</script>

<style scoped>
:root {
  --primary-color: #4f46e5;
  --primary-hover: #4338ca;
  --primary-dark: #3730a3;
  --secondary-color: #64748b;
  --secondary-hover: #475569;
  --secondary-dark: #334155;
  --success-color: #059669;
  --success-hover: #047857;
  --success-dark: #065f46;
  --surface-color: #f8fafc;
}

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
  border: 1px solid #e5e9f2;
  border-radius: 0.75rem;
  margin-bottom: 1.5rem;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
  transition: box-shadow 0.2s ease;
}

.card:hover {
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
}

.card-header {
  background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);
  border-bottom: 1px solid #e5e9f2;
  padding: 1rem 1.25rem;
  border-radius: 0.75rem 0.75rem 0 0;
}

.card-body {
  padding: 1.25rem;
}

/* Main component card styling */
.card-body > .card {
  background: #ffffff;
}

.card-body > .card:last-child {
  margin-bottom: 0;
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

.component-metadata-header {
  padding-bottom: 1rem;
  border-bottom: 1px solid #eaecef;
  margin-bottom: 1.5rem !important;
}

.component-metadata-header h4 {
  color: #2c3e50;
  font-weight: 600;
  font-size: 1.5rem;
}

.augmentation-notice {
  font-size: 0.9rem;
  background: #f8fafc;
  padding: 0.5rem 0.75rem;
  border-radius: 0.375rem;
  border-left: 3px solid #4f46e5;
}

.augmentation-notice i {
  font-size: 1rem;
}

.btn {
  border-radius: 0.375rem;
  font-weight: 500;
  transition: all 0.2s ease;
}

.btn-primary {
  background: #4f46e5;
  border: 1px solid #4338ca;
  color: white;
  font-weight: 600;
  box-shadow: 0 2px 4px rgba(79, 70, 229, 0.2);
}

.btn-primary:hover {
  background: #4338ca;
  border-color: #3730a3;
  color: white;
  box-shadow: 0 4px 8px rgba(79, 70, 229, 0.3);
  transform: translateY(-1px);
}

.btn-primary:focus {
  background: #4338ca;
  border-color: #3730a3;
  color: white;
  box-shadow: 0 0 0 0.2rem rgba(79, 70, 229, 0.25);
}

.btn-secondary {
  background: #64748b;
  border: 1px solid #475569;
  color: white;
  font-weight: 600;
  box-shadow: 0 2px 4px rgba(100, 116, 139, 0.2);
}

.btn-secondary:hover {
  background: #475569;
  border-color: #334155;
  color: white;
  box-shadow: 0 4px 8px rgba(100, 116, 139, 0.3);
  transform: translateY(-1px);
}

.btn-secondary:focus {
  background: #475569;
  border-color: #334155;
  color: white;
  box-shadow: 0 0 0 0.2rem rgba(100, 116, 139, 0.25);
}

.btn-success {
  background: #16a34a;
  border: 1px solid #15803d;
  color: white;
  font-weight: 600;
  box-shadow: 0 2px 4px rgba(22, 163, 74, 0.2);
}

.btn-success:hover {
  background: #15803d;
  border-color: #166534;
  color: white;
  box-shadow: 0 4px 8px rgba(22, 163, 74, 0.3);
  transform: translateY(-1px);
}

.btn-success:focus {
  background: #15803d;
  border-color: #166534;
  color: white;
  box-shadow: 0 0 0 0.2rem rgba(22, 163, 74, 0.25);
}

.btn-success:disabled {
  background: #9ca3af;
  border-color: #9ca3af;
  color: white;
  opacity: 0.65;
  cursor: not-allowed;
  box-shadow: none;
  transform: none;
}

.btn-outline-secondary {
  border: 2px solid #64748b;
  color: #64748b;
  background: transparent;
  font-weight: 600;
  transition: all 0.2s ease;
}

.btn-outline-secondary:hover {
  background: #64748b;
  border-color: #64748b;
  color: white;
  box-shadow: 0 2px 4px rgba(100, 116, 139, 0.2);
  transform: translateY(-1px);
}

.btn-outline-secondary:focus {
  background: #64748b;
  border-color: #64748b;
  color: white;
  box-shadow: 0 0 0 0.2rem rgba(100, 116, 139, 0.25);
}

.actions-section {
  border-top: 1px solid #e5e9f2 !important;
  background: #f8f9fa;
  margin: 0 -1.25rem -1.25rem -1.25rem;
  padding: 1.5rem 1.25rem 1.25rem 1.25rem;
  border-radius: 0 0 0.75rem 0.75rem;
}

.btn-lg {
  padding: 0.75rem 1.5rem;
  font-size: 1rem;
  font-weight: 600;
}
</style>

