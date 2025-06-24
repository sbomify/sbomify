<template>
  <StandardCard
    title="Branding"
    variant="settings"
    size="large"
    shadow="md"
  >
    <p class="mb-4">Set default brand elements to determine how public SBOMs appear.</p>

    <v-skeleton-loader
      v-show="isLoading"
      type="article"
      class="mb-4"
    ></v-skeleton-loader>

    <div v-show="!isLoading">
      <div class="row form-field">
        <div class="col-md-3 col-6">
          <label for="brand_color" class="form-label">Brand color</label>
        </div>
        <div class="col-md-2 col-3">
          <div class="color-picker-wrapper">
            <input v-model="brandingInfo.brand_color" type="text" class="form-control color-text"
              placeholder="#000000" @input="validateAndUpdateColor($event, 'brand_color')">
            <input v-model="brandingInfo.brand_color" type="color" class="form-control color-picker" @change="updateField('brand_color')">
          </div>
        </div>
      </div>

      <div class="row form-field">
        <div class="col-md-3 col-6">
          <label for="accent_color" class="form-label">Accent color</label>
        </div>
        <div class="col-md-2 col-3">
          <div class="color-picker-wrapper">
            <input v-model="brandingInfo.accent_color" type="text" class="form-control color-text"
              placeholder="#000000" @input="validateAndUpdateColor($event, 'accent_color')">
            <input v-model="brandingInfo.accent_color" type="color" class="form-control color-picker" @change="updateField('accent_color')">
          </div>
        </div>
      </div>

      <div class="row form-field">
        <div class="col-md-3 col-6">
          <label for="icon" class="form-label">Icon</label>
        </div>
        <div class="col-md-2 col-3">
          <FileDragAndDrop v-model="brandingInfo.icon" accept="image/*" @update:modelValue="handleFileUpload('icon', $event)" />
        </div>
      </div>

      <div class="row form-field">
        <div class="col-md-3 col-6">
          <label for="logo" class="form-label">Logo</label>
        </div>
        <div class="col-md-2 col-3">
          <FileDragAndDrop v-model="brandingInfo.logo" accept="image/*" @update:modelValue="handleFileUpload('logo', $event)" />
        </div>
      </div>

      <div class="row form-field">
        <div class="col-md-3 col-6">
          <label for="prefer_logo_over_icon_switch" class="form-label d-flex align-items-center h-100">Prefer logo over icon</label>
        </div>
        <div class="col-md-2 col-3">
          <v-switch id="prefer_logo_over_icon_switch" v-model="brandingInfo.prefer_logo_over_icon"
            hide-details density="compact" color="primary" inset @change="updateField('prefer_logo_over_icon')"></v-switch>
        </div>
      </div>
    </div>
  </StandardCard>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue';
import { isAxiosError } from 'axios';
import $axios from '../../../core/js/utils';
import FileDragAndDrop from '../../../core/js/components/FileDragAndDrop.vue';
import StandardCard from '../../../core/js/components/StandardCard.vue';
import { showSuccess, showError } from '../../../core/js/alerts';

interface Props {
  teamKey: string;
}

interface BrandingInfo {
  brand_color: string;
  accent_color: string;
  icon: File | null;
  logo: File | null;
  icon_url: string;
  logo_url: string;
  prefer_logo_over_icon: boolean;
  [key: string]: string | boolean | File | null;
}

const props = defineProps<Props>();
const isLoading = ref(true);
const brandingInfo = ref<BrandingInfo>({
  brand_color: "",
  accent_color: "",
  icon: null,
  logo: null,
  icon_url: "",
  logo_url: "",
  prefer_logo_over_icon: false
});

const handleFileUpload = async (field: string, file: File | null | undefined) => {
  if (!file) return;

  const formData = new FormData();
  formData.append(field, file);

  try {
    const response = await $axios.post(`/api/v1/teams/${props.teamKey}/branding/${field}`, formData, {
      headers: {
        'Content-Type': 'multipart/form-data'
      }
    });

    if (response.status < 200 || response.status >= 300) {
      throw new Error('Network response was not ok. ' + response.statusText);
    }

    await showSuccess('File uploaded successfully');
  } catch (error: unknown) {
    console.log(error);
    if (isAxiosError(error)) {
      showError(`${error.response?.status} - ${error.response?.statusText}: ${error.response?.data?.detail[0].msg}`);
    } else {
      showError('Failed to upload file');
    }
  }
};

const updateField = async (field: string) => {
  try {
    const response = await $axios.post(`/api/v1/teams/${props.teamKey}/branding/${field}`, {
      [field]: brandingInfo.value[field]
    });

    if (response.status < 200 || response.status >= 300) {
      throw new Error('Network response was not ok. ' + response.statusText);
    }

    await showSuccess('Setting updated successfully');
  } catch (error: unknown) {
    console.log(error);
    if (isAxiosError(error)) {
      showError(`${error.response?.status} - ${error.response?.statusText}: ${error.response?.data?.detail[0].msg}`);
    } else {
      showError('Failed to update setting');
    }
  }
};

const validateAndUpdateColor = async (event: Event, field: 'brand_color' | 'accent_color') => {
  const input = event.target as HTMLInputElement;
  const colorValue = input.value;
  if (/^#[0-9A-F]{6}$/i.test(colorValue)) {
    brandingInfo.value[field] = colorValue;
    await updateField(field);
  }
};

const loadImagesFromUrls = async () => {
  if (brandingInfo.value.icon_url) {
    try {
      const iconResponse = await fetch(brandingInfo.value.icon_url);
      const iconBlob = await iconResponse.blob();
      brandingInfo.value.icon = new File([iconBlob], 'icon', { type: iconBlob.type });
    } catch (error) {
      console.error('Failed to load icon:', error);
    }
  }

  if (brandingInfo.value.logo_url) {
    try {
      const logoResponse = await fetch(brandingInfo.value.logo_url);
      const logoBlob = await logoResponse.blob();
      brandingInfo.value.logo = new File([logoBlob], 'logo', { type: logoBlob.type });
    } catch (error) {
      console.error('Failed to load logo:', error);
    }
  }
};

onMounted(async () => {
  try {
    const response = await $axios.get(`/api/v1/teams/${props.teamKey}/branding`);
    brandingInfo.value = response.data;
    await loadImagesFromUrls();
  } catch (error: unknown) {
    console.log(error);
    if (isAxiosError(error)) {
      showError(`${error.response?.status} - ${error.response?.statusText}: ${error.response?.data?.detail[0].msg}`);
    } else {
      showError('Failed to load branding settings');
    }
  } finally {
    isLoading.value = false;
  }
});
</script>

<style scoped>
.form-field {
  margin-bottom: 1.5rem;
  align-items: center;
}

.form-label {
  font-weight: 600;
  color: #374151;
  margin-bottom: 0;
  font-size: 0.95rem;
}

.color-picker-wrapper {
  position: relative;
  display: flex;
  align-items: center;
}

.color-picker {
  width: 40px;
  height: 38px;
  padding: 0;
  margin-left: 8px;
  border: 1px solid #d1d5db;
  border-radius: 0.375rem;
  cursor: pointer;
}

.color-text {
  width: 100px;
  padding: 0.5rem 0.75rem;
  border: 1px solid #d1d5db;
  border-radius: 0.375rem;
  font-size: 0.875rem;
  transition: border-color 0.15s ease-in-out, box-shadow 0.15s ease-in-out;
}

.color-text:focus {
  border-color: #3b82f6;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
  outline: none;
}

/* Responsive adjustments */
@media (max-width: 768px) {
  .form-field {
    flex-direction: column;
    align-items: flex-start;
    text-align: left;
  }

  .form-label {
    margin-bottom: 0.5rem;
  }

  .color-picker-wrapper {
    width: 100%;
    justify-content: flex-start;
  }
}

:deep(.floating-alert) {
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15) !important;
}
</style>