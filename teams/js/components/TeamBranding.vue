<style scoped>
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
  }

  .color-text {
    width: 100px;
  }

  .alert {
    margin-bottom: 1rem;
    position: relative;
  }

  .alert-outline-coloured {
    border: none;
    border-radius: 0.5rem;
    padding: 1rem;
    display: flex;
    align-items: center;
    gap: 0.5rem;
  }

  .alert-success {
    background-color: rgba(40, 167, 69, 0.1);
    border-left: 3px solid var(--bs-success);
  }

  .alert-danger {
    background-color: rgba(220, 53, 69, 0.1);
    border-left: 3px solid var(--bs-danger);
  }

  .alert-icon {
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 1.25rem;
    width: 2rem;
    margin-right: 0.5rem;
  }

  .alert-success .alert-icon {
    color: var(--bs-success);
  }

  .alert-danger .alert-icon {
    color: var(--bs-danger);
  }

  .alert-message {
    flex-grow: 1;
    display: flex;
    align-items: center;
    font-weight: 500;
    font-size: 0.875rem;
    line-height: 1.5;
    margin-right: 0.5rem;
  }

  .btn-close {
    padding: 0.25rem;
    margin: 0;
    border-radius: 4px;
    opacity: 0.5;
    transition: all 0.15s ease-in-out;
    display: flex;
    align-items: center;
    justify-content: center;
    width: 1.5rem;
    height: 1.5rem;
    background: none;
    border: 0;
    cursor: pointer;
  }

  .btn-close:hover {
    opacity: 1;
    background: var(--bs-gray-100);
  }

  :deep(.floating-alert) {
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15) !important;
  }
</style>

<template>
  <div class="card">
    <div class="card-body">
      <h4 class="p-1 text-black">Branding</h4>
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
              <input type="text" class="form-control color-text" v-model="brandingInfo.brand_color"
                placeholder="#000000" @input="validateAndUpdateColor($event, 'brand_color')">
              <input type="color" class="form-control color-picker" v-model="brandingInfo.brand_color" @change="updateField('brand_color')">
            </div>
          </div>
        </div>

        <div class="row form-field">
          <div class="col-md-3 col-6">
            <label for="accent_color" class="form-label">Accent color</label>
          </div>
          <div class="col-md-2 col-3">
            <div class="color-picker-wrapper">
              <input type="text" class="form-control color-text" v-model="brandingInfo.accent_color"
                placeholder="#000000" @input="validateAndUpdateColor($event, 'accent_color')">
              <input type="color" class="form-control color-picker" v-model="brandingInfo.accent_color" @change="updateField('accent_color')">
            </div>
          </div>
        </div>

        <div class="row form-field">
          <div class="col-md-3 col-6">
            <label for="icon" class="form-label">Icon</label>
          </div>
          <div class="col-md-2 col-3">
            <FileDragAndDrop accept="image/*" v-model="brandingInfo.icon" @update:modelValue="handleFileUpload('icon', $event)" />
          </div>
        </div>

        <div class="row form-field">
          <div class="col-md-3 col-6">
            <label for="logo" class="form-label">Logo</label>
          </div>
          <div class="col-md-2 col-3">
            <FileDragAndDrop accept="image/*" v-model="brandingInfo.logo" @update:modelValue="handleFileUpload('logo', $event)" />
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
    </div>
  </div>
</template>

<script setup lang="ts">
  import { ref, onMounted } from 'vue';
  import $axios from '../../../core/js/utils';
  import FileDragAndDrop from '../../../core/js/components/FileDragAndDrop.vue';
  import Swal from 'sweetalert2';

  interface Props {
    teamKey: string;
  }

  const props = defineProps<Props>();
  const isLoading = ref(true);

  interface BrandingInfo {
    brand_color: string;
    accent_color: string;
    icon: File | null;
    logo: File | null;
    icon_url: string;
    logo_url: string;
    prefer_logo_over_icon: boolean;
  }

  const Toast = Swal.mixin({
    toast: true,
    position: 'top-end',
    showConfirmButton: false,
    timer: 3000,
    timerProgressBar: true,
    didOpen: (toast) => {
      toast.addEventListener('mouseenter', Swal.stopTimer);
      toast.addEventListener('mouseleave', Swal.resumeTimer);
    }
  });

  const brandingInfo = ref<BrandingInfo>({
    brand_color: "",
    accent_color: "",
    icon: null,
    logo: null,
    icon_url: "",
    logo_url: "",
    prefer_logo_over_icon: false
  });

  const showSuccess = (message: string) => {
    Toast.fire({
      icon: 'success',
      title: message
    });
  };

  const showError = (message: string) => {
    Toast.fire({
      icon: 'error',
      title: message
    });
  };

  const apiUrl = '/api/v1/teams/' + props.teamKey + '/branding';

  const loadImagesFromUrls = async (data: any) => {
    const newBrandingInfo: BrandingInfo = {
      brand_color: data.brand_color,
      accent_color: data.accent_color,
      icon: null,
      logo: null,
      icon_url: data.icon_url,
      logo_url: data.logo_url,
      prefer_logo_over_icon: data.prefer_logo_over_icon
    };

    if (data.icon_url) {
      try {
        const iconResponse = await fetch(data.icon_url);
        const iconBlob = await iconResponse.blob();
        const filename = data.icon_url.split('/').pop() || '';
        newBrandingInfo.icon = new File([iconBlob], filename);
      } catch (error) {
        console.error('Failed to load icon:', error);
      }
    }

    if (data.logo_url) {
      try {
        const logoResponse = await fetch(data.logo_url);
        const logoBlob = await logoResponse.blob();
        const filename = data.logo_url.split('/').pop() || '';
        newBrandingInfo.logo = new File([logoBlob], filename, { type: logoBlob.type });
      } catch (error) {
        console.error('Failed to load logo:', error);
      }
    }

    return newBrandingInfo;
  };

  onMounted(async () => {
    try {
      const response = await $axios.get(apiUrl);
      brandingInfo.value = await loadImagesFromUrls(response.data);
    } catch (error) {
      console.error('Failed to fetch branding info:', error);
      showError('Failed to load branding information');
    } finally {
      isLoading.value = false;
    }
  });

  const validateAndUpdateColor = async (event: Event, field: 'brand_color' | 'accent_color') => {
    const input = event.target as HTMLInputElement;
    const colorValue = input.value;
    if (/^#[0-9A-F]{6}$/i.test(colorValue)) {
      brandingInfo.value[field] = colorValue;
      await updateField(field);
    }
  };

  const updateField = async (field: string) => {
    try {
      const value = brandingInfo.value[field as keyof BrandingInfo];
      const response = await $axios.patch(`${apiUrl}/${field}`, { value });
      brandingInfo.value = await loadImagesFromUrls(response.data);
      showSuccess(`${field.replace('_', ' ')} updated successfully`);
    } catch (error) {
      console.error(`Failed to update ${field}:`, error);
      showError(`Failed to update ${field.replace('_', ' ')}`);
    }
  };

  const handleFileUpload = async (fileType: 'icon' | 'logo', file: File | null) => {
    try {
      if (file) {
        const formData = new FormData();
        formData.append('file', file);

        const response = await $axios.post(
          `${apiUrl}/upload/${fileType}`,
          formData,
          {
            headers: {
              'Content-Type': 'multipart/form-data'
            }
          }
        );

        brandingInfo.value = await loadImagesFromUrls(response.data);
        showSuccess(`${fileType} uploaded successfully`);
      } else {
        // Handle file deletion by setting the field to null
        const response = await $axios.patch(`${apiUrl}/${fileType}`, { value: null });
        brandingInfo.value = await loadImagesFromUrls(response.data);
        showSuccess(`${fileType} removed successfully`);
      }
    } catch (error) {
      console.error(`Failed to upload ${fileType}:`, error);
      showError(`Failed to ${file ? 'upload' : 'remove'} ${fileType}`);
    }
  };
</script>

