<template>
  <StandardCard
    title="Workspace Branding"
    variant="settings"
    size="large"
    shadow="md"
  >
    <p class="subtitle mb-5">Customize your workspace's visual identity for public SBOMs and shared content.</p>

    <div v-show="isLoading" class="skeleton-loader mb-4">
      <div class="skeleton-card">
        <div class="skeleton-header">
          <div class="skeleton-line skeleton-title"></div>
          <div class="skeleton-line skeleton-subtitle"></div>
        </div>
        <div class="skeleton-content">
          <div class="row g-3">
            <div class="col-md-6">
              <div class="skeleton-line skeleton-field"></div>
            </div>
            <div class="col-md-6">
              <div class="skeleton-line skeleton-field"></div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div v-show="!isLoading" class="branding-form">
      <!-- Colors Section -->
      <div class="section-card">
        <div class="section-header">
          <h3 class="section-title">Brand Colors</h3>
          <p class="section-description">Define your primary brand colors for consistent visual identity.</p>
        </div>
        <div class="section-content">
          <div class="row g-4">
            <div class="col-md-6">
              <div class="color-field">
                <label for="brand_color" class="field-label">Primary Brand Color</label>
                <div class="color-input-group">
                  <div class="color-preview" :style="{ backgroundColor: brandingInfo.brand_color || '#000000' }"></div>
                  <input
                    v-model="brandingInfo.brand_color"
                    type="text"
                    class="form-control color-text"
                    placeholder="#000000"
                    @input="validateAndUpdateColor($event, 'brand_color')"
                  >
                  <input
                    v-model="brandingInfo.brand_color"
                    type="color"
                    class="color-picker"
                    @change="updateField('brand_color')"
                  >
                </div>
                <small class="field-hint">Used for primary branding elements and headers</small>
              </div>
            </div>
            <div class="col-md-6">
              <div class="color-field">
                <label for="accent_color" class="field-label">Accent Color</label>
                <div class="color-input-group">
                  <div class="color-preview" :style="{ backgroundColor: brandingInfo.accent_color || '#000000' }"></div>
                  <input
                    v-model="brandingInfo.accent_color"
                    type="text"
                    class="form-control color-text"
                    placeholder="#000000"
                    @input="validateAndUpdateColor($event, 'accent_color')"
                  >
                  <input
                    v-model="brandingInfo.accent_color"
                    type="color"
                    class="color-picker"
                    @change="updateField('accent_color')"
                  >
                </div>
                <small class="field-hint">Used for buttons, links, and highlights</small>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Visual Assets Section -->
      <div class="section-card">
        <div class="section-header">
          <h3 class="section-title">Visual Assets</h3>
          <p class="section-description">Upload your brand assets to personalize the appearance of public content.</p>
        </div>
        <div class="section-content">
          <div class="row g-4">
            <div class="col-md-6">
              <div class="upload-field">
                <label class="field-label">Brand Icon</label>
                <div class="upload-container">
                                     <FileDragAndDrop
                     v-model="brandingInfo.icon"
                     accept="image/*"
                     class="modern-upload"
                     @update:modelValue="(file) => handleFileUpload('icon', file || null)"
                   />
                </div>
                <small class="field-hint">Recommended: 512x512px PNG or SVG. Used in headers and navigation.</small>
              </div>
            </div>
            <div class="col-md-6">
              <div class="upload-field">
                <label class="field-label">Brand Logo</label>
                <div class="upload-container">
                                     <FileDragAndDrop
                     v-model="brandingInfo.logo"
                     accept="image/*"
                     class="modern-upload"
                     @update:modelValue="(file) => handleFileUpload('logo', file || null)"
                   />
                </div>
                <small class="field-hint">Recommended: 1200x300px PNG or SVG. Used for larger brand displays.</small>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Preferences Section -->
      <div class="section-card">
        <div class="section-header">
          <h3 class="section-title">Display Preferences</h3>
          <p class="section-description">Configure how your brand assets are displayed across the platform.</p>
        </div>
        <div class="section-content">
          <div class="preference-row">
            <div class="preference-content">
              <label for="prefer_logo_over_icon_switch" class="preference-label">Prefer Logo Over Icon</label>
              <p class="preference-description">When both logo and icon are available, prioritize showing the logo in branding areas.</p>
            </div>
            <div class="preference-control">
              <div class="form-check form-switch">
                <input
                  id="prefer_logo_over_icon_switch"
                  v-model="brandingInfo.prefer_logo_over_icon"
                  class="form-check-input"
                  type="checkbox"
                  role="switch"
                  @change="updateField('prefer_logo_over_icon')"
                >
                <label class="form-check-label" for="prefer_logo_over_icon_switch"></label>
              </div>
            </div>
          </div>
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

const validateAndUpdateColor = (event: Event, field: string) => {
  const target = event.target as HTMLInputElement;
  let value = target.value;

  // Add # if not present and value is not empty
  if (value && !value.startsWith('#')) {
    value = '#' + value;
    target.value = value;
  }

  // Validate hex color format
  const hexPattern = /^#([0-9A-Fa-f]{3}|[0-9A-Fa-f]{6})$/;
  if (value === '' || hexPattern.test(value)) {
    brandingInfo.value[field] = value;
    updateField(field);
  }
};

const updateField = async (field: string) => {
  try {
    const payload: Record<string, unknown> = {};
    payload[field] = brandingInfo.value[field];

    await $axios.patch(`/api/v1/teams/${props.teamKey}/branding`, payload);
    showSuccess('Branding updated successfully');
  } catch (error) {
    console.error('Error updating branding:', error);
    if (isAxiosError(error)) {
      showError(error.response?.data?.message || 'Failed to update branding');
    } else {
      showError('Failed to update branding');
    }
  }
};

const handleFileUpload = async (field: string, file: File | null) => {
  if (!file) return;

  try {
    const formData = new FormData();
    formData.append(field, file);

    await $axios.patch(`/api/v1/teams/${props.teamKey}/branding`, formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    });

    showSuccess(`${field.charAt(0).toUpperCase() + field.slice(1)} uploaded successfully`);
  } catch (error) {
    console.error(`Error uploading ${field}:`, error);
    if (isAxiosError(error)) {
      showError(error.response?.data?.message || `Failed to upload ${field}`);
    } else {
      showError(`Failed to upload ${field}`);
    }
  }
};

onMounted(async () => {
  try {
    const response = await $axios.get(`/api/v1/teams/${props.teamKey}/branding`);
    if (response.data) {
      Object.assign(brandingInfo.value, response.data);
    }
  } catch (error) {
    console.error('Error loading branding info:', error);
    if (isAxiosError(error)) {
      showError(error.response?.data?.message || 'Failed to load branding information');
    } else {
      showError('Failed to load branding information');
    }
  } finally {
    isLoading.value = false;
  }
});
</script>

<style scoped>
.subtitle {
  color: #6b7280;
  font-size: 1rem;
  line-height: 1.5;
}

.branding-form {
  display: flex;
  flex-direction: column;
  gap: 2rem;
}

/* Section Cards */
.section-card {
  background: #f8fafc;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  overflow: hidden;
  transition: all 0.2s ease;
}

.section-card:hover {
  border-color: #d1d5db;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
}

.section-header {
  padding: 1.5rem 1.5rem 1rem;
  background: linear-gradient(135deg, #ffffff, #f9fafb);
  border-bottom: 1px solid #e5e7eb;
}

.section-title {
  font-size: 1.125rem;
  font-weight: 600;
  color: #111827;
  margin: 0 0 0.5rem 0;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.section-description {
  color: #6b7280;
  font-size: 0.875rem;
  margin: 0;
  line-height: 1.4;
}

.section-content {
  padding: 1.5rem;
}

/* Form Fields */
.field-label {
  display: block;
  font-weight: 600;
  color: #374151;
  margin-bottom: 0.5rem;
  font-size: 0.875rem;
  letter-spacing: 0.01em;
}

.field-hint {
  color: #6b7280;
  font-size: 0.75rem;
  line-height: 1.4;
  margin-top: 0.5rem;
  display: block;
}

/* Color Fields */
.color-field {
  position: relative;
}

.color-input-group {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  background: white;
  border: 1px solid #d1d5db;
  border-radius: 8px;
  padding: 0.5rem;
  transition: all 0.2s ease;
}

.color-input-group:focus-within {
  border-color: #3b82f6;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
}

.color-preview {
  width: 32px;
  height: 32px;
  border-radius: 6px;
  border: 2px solid #e5e7eb;
  flex-shrink: 0;
  transition: border-color 0.2s ease;
}

.color-text {
  flex: 1;
  border: none;
  outline: none;
  background: transparent;
  padding: 0.25rem 0.5rem;
  font-family: 'SF Mono', 'Monaco', 'Inconsolata', 'Fira Code', monospace;
  font-size: 0.875rem;
  color: #374151;
}

.color-picker {
  width: 32px;
  height: 32px;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  background: none;
  padding: 0;
  flex-shrink: 0;
}

.color-picker::-webkit-color-swatch-wrapper {
  padding: 0;
  border-radius: 6px;
  overflow: hidden;
}

.color-picker::-webkit-color-swatch {
  border: none;
  border-radius: 6px;
}

/* Upload Fields */
.upload-field {
  position: relative;
}

.upload-container {
  border-radius: 8px;
  overflow: hidden;
}

/* Override FileDragAndDrop default styling completely */
:deep(.modern-upload) {
  border: none !important;
  background: transparent !important;
  padding: 0 !important;
  min-height: 160px;
}

:deep(.modern-upload .file-upload-container) {
  width: 100%;
}

:deep(.modern-upload .drop-zone) {
  border: 2px dashed #d1d5db !important;
  border-radius: 8px !important;
  background: white !important;
  padding: 2rem !important;
  min-height: 160px !important;
  transition: all 0.2s ease !important;
  display: flex !important;
  align-items: center !important;
  justify-content: center !important;
}

:deep(.modern-upload .drop-zone):hover {
  border-color: #9ca3af !important;
  background: #f9fafb !important;
}

:deep(.modern-upload .drop-zone.has-file) {
  border-style: dashed !important;
}

/* Preferences */
.preference-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1.5rem;
  background: white;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 1.25rem;
  transition: all 0.2s ease;
}

.preference-row:hover {
  border-color: #d1d5db;
  background: #f9fafb;
}

.preference-content {
  flex: 1;
}

.preference-label {
  display: block;
  font-weight: 600;
  color: #374151;
  margin: 0 0 0.25rem 0;
  font-size: 0.875rem;
}

.preference-description {
  color: #6b7280;
  font-size: 0.8rem;
  margin: 0;
  line-height: 1.4;
}

.preference-control {
  flex-shrink: 0;
  display: flex;
  align-items: center;
}

/* Responsive Design */
@media (max-width: 768px) {
  .section-content {
    padding: 1rem;
  }

  .section-header {
    padding: 1rem 1rem 0.75rem;
  }

  .color-input-group {
    flex-direction: column;
    align-items: stretch;
    gap: 0.5rem;
    padding: 0.75rem;
  }

  .color-preview {
    align-self: center;
  }

  .preference-row {
    flex-direction: column;
    gap: 1rem;
    align-items: stretch;
  }

  .preference-control {
    justify-content: flex-start;
  }
}

@media (max-width: 576px) {
  .branding-form {
    gap: 1.5rem;
  }

  .section-card {
    border-radius: 8px;
  }

  .section-content {
    padding: 0.75rem;
  }
}

/* Skeleton Loader */
.skeleton-loader {
  animation: pulse 1.5s ease-in-out infinite;
}

.skeleton-card {
  background: #f8fafc;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  overflow: hidden;
}

.skeleton-header {
  padding: 1.5rem 1.5rem 1rem;
  background: linear-gradient(135deg, #ffffff, #f9fafb);
  border-bottom: 1px solid #e5e7eb;
}

.skeleton-content {
  padding: 1.5rem;
}

.skeleton-line {
  background: linear-gradient(90deg, #e5e7eb 25%, #f3f4f6 50%, #e5e7eb 75%);
  background-size: 200% 100%;
  animation: shimmer 1.5s infinite;
  border-radius: 4px;
  margin-bottom: 0.75rem;
}

.skeleton-title {
  height: 1.5rem;
  width: 60%;
  margin-bottom: 0.5rem;
}

.skeleton-subtitle {
  height: 1rem;
  width: 80%;
  margin-bottom: 0;
}

.skeleton-field {
  height: 2.5rem;
  width: 100%;
}

@keyframes shimmer {
  0% {
    background-position: -200% 0;
  }
  100% {
    background-position: 200% 0;
  }
}

@keyframes pulse {
  0%, 100% {
    opacity: 1;
  }
  50% {
    opacity: 0.8;
  }
}

/* Switch Styling */
.form-check.form-switch {
  min-height: auto;
  padding-left: 0;
}

.form-check.form-switch .form-check-input {
  width: 3rem;
  height: 1.5rem;
  margin-left: 0;
  background-color: #e5e7eb;
  border: 1px solid #d1d5db;
  transition: all 0.2s ease;
}

.form-check.form-switch .form-check-input:checked {
  background-color: #3b82f6;
  border-color: #3b82f6;
}

.form-check.form-switch .form-check-input:focus {
  box-shadow: 0 0 0 0.25rem rgba(59, 130, 246, 0.25);
  border-color: #3b82f6;
}

/* Floating Alert Styling */
:deep(.floating-alert) {
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15) !important;
}
</style>