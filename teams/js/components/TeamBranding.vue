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
                  <input
                    v-model="localBrandingInfo.brand_color"
                    type="color"
                    class="color-picker-modern"
                    @input="handleColorPickerChange($event, 'brand_color')"
                  >
                  <div class="color-info">
                    <span class="color-hex">{{ localBrandingInfo.brand_color || 'Not set' }}</span>
                    <small class="color-hint">Click to choose color</small>
                  </div>
                </div>
                <small class="field-hint">Used for primary branding elements and headers</small>
              </div>
            </div>
            <div class="col-md-6">
              <div class="color-field">
                <label for="accent_color" class="field-label">Accent Color</label>
                <div class="color-input-group">
                  <input
                    v-model="localBrandingInfo.accent_color"
                    type="color"
                    class="color-picker-modern"
                    @input="handleColorPickerChange($event, 'accent_color')"
                  >
                  <div class="color-info">
                    <span class="color-hex">{{ localBrandingInfo.accent_color || 'Not set' }}</span>
                    <small class="color-hint">Click to choose color</small>
                  </div>
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
                     v-model="localBrandingInfo.icon"
                     accept="image/*"
                     class="modern-upload"
                     @update:modelValue="(file) => handleFileChange('icon', file || null)"
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
                     v-model="localBrandingInfo.logo"
                     accept="image/*"
                     class="modern-upload"
                     @update:modelValue="(file) => handleFileChange('logo', file || null)"
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
              <label for="prefer_logo_over_icon_switch" class="preference-label">Primary Brand Asset</label>
              <p class="preference-description">
                When you upload both an icon and logo, choose which one takes priority in public pages.
                <br><strong>Icon:</strong> Better for compact spaces (headers, favicons)
                <br><strong>Logo:</strong> Better for prominent branding areas
              </p>
            </div>
            <div class="preference-control">
              <div class="form-check form-switch">
                <input
                  id="prefer_logo_over_icon_switch"
                  v-model="localBrandingInfo.prefer_logo_over_icon"
                  class="form-check-input"
                  type="checkbox"
                  role="switch"
                >
                <label class="form-check-label" for="prefer_logo_over_icon_switch"></label>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Save Actions -->
    <div class="save-actions">
      <button
        v-if="hasUnsavedChanges && !isSaving"
        class="btn btn-outline-secondary btn-cancel"
        @click="resetChanges"
      >
        <i class="fas fa-undo me-2"></i>
        Cancel
      </button>
      <button
        v-if="hasUnsavedChanges"
        :disabled="isSaving"
        class="btn btn-primary btn-save"
        @click="saveAllChanges"
      >
        <i class="fas fa-save me-2"></i>
        {{ isSaving ? 'Saving...' : 'Save Changes' }}
      </button>
    </div>
  </StandardCard>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue';
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
const isSaving = ref(false);

// Original server data
const brandingInfo = ref<BrandingInfo>({
  brand_color: "",
  accent_color: "",
  icon: null,
  logo: null,
  icon_url: "",
  logo_url: "",
  prefer_logo_over_icon: false
});

// Local form state
const localBrandingInfo = ref<BrandingInfo>({
  brand_color: "",
  accent_color: "",
  icon: null,
  logo: null,
  icon_url: "",
  logo_url: "",
  prefer_logo_over_icon: false
});

// Track changes
const hasUnsavedChanges = computed(() => {
  if (isLoading.value) return false;

  // Compare with original server values (not defaults)
  const originalBrandColor = brandingInfo.value.brand_color || '';
  const originalAccentColor = brandingInfo.value.accent_color || '';
  const currentBrandColor = localBrandingInfo.value.brand_color || '';
  const currentAccentColor = localBrandingInfo.value.accent_color || '';

  return (
    currentBrandColor !== originalBrandColor ||
    currentAccentColor !== originalAccentColor ||
    localBrandingInfo.value.prefer_logo_over_icon !== brandingInfo.value.prefer_logo_over_icon ||
    localBrandingInfo.value.icon !== null ||
    localBrandingInfo.value.logo !== null
  );
});



const handleColorPickerChange = (event: Event, field: string) => {
  const target = event.target as HTMLInputElement;
  localBrandingInfo.value[field] = target.value;
};

const handleFileChange = (field: string, file: File | null) => {
  localBrandingInfo.value[field] = file;
};

const resetChanges = () => {
  console.log('Resetting changes...');
  console.log('Original server data:', brandingInfo.value);

  // Reset local state to exactly match server state
  Object.assign(localBrandingInfo.value, {
    brand_color: brandingInfo.value.brand_color || '',
    accent_color: brandingInfo.value.accent_color || '',
    prefer_logo_over_icon: brandingInfo.value.prefer_logo_over_icon,
    icon_url: brandingInfo.value.icon_url || '',
    logo_url: brandingInfo.value.logo_url || '',
    icon: null, // Always reset file uploads
    logo: null, // Always reset file uploads
  });

  console.log('Reset to:', localBrandingInfo.value);
};

const saveAllChanges = async () => {
  if (!hasUnsavedChanges.value || isSaving.value) return;

  isSaving.value = true;

  try {
    // Save individual field changes using the correct API endpoints
    if (localBrandingInfo.value.brand_color !== brandingInfo.value.brand_color) {
      await $axios.patch(`/api/v1/teams/${props.teamKey}/branding/brand_color`, {
        value: localBrandingInfo.value.brand_color
      });
    }

    if (localBrandingInfo.value.accent_color !== brandingInfo.value.accent_color) {
      await $axios.patch(`/api/v1/teams/${props.teamKey}/branding/accent_color`, {
        value: localBrandingInfo.value.accent_color
      });
    }

    if (localBrandingInfo.value.prefer_logo_over_icon !== brandingInfo.value.prefer_logo_over_icon) {
      await $axios.patch(`/api/v1/teams/${props.teamKey}/branding/prefer_logo_over_icon`, {
        value: localBrandingInfo.value.prefer_logo_over_icon
      });
    }

    // Upload new files using the correct upload endpoints
    if (localBrandingInfo.value.icon) {
      const iconFormData = new FormData();
      iconFormData.append('file', localBrandingInfo.value.icon);
      await $axios.post(`/api/v1/teams/${props.teamKey}/branding/upload/icon`, iconFormData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
    }

    if (localBrandingInfo.value.logo) {
      const logoFormData = new FormData();
      logoFormData.append('file', localBrandingInfo.value.logo);
      await $axios.post(`/api/v1/teams/${props.teamKey}/branding/upload/logo`, logoFormData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
    }

    // Reload the current data from server
    const response = await $axios.get(`/api/v1/teams/${props.teamKey}/branding`);
    if (response.data) {
      Object.assign(brandingInfo.value, response.data);
      // Reset local state to match server
      Object.assign(localBrandingInfo.value, {
        ...response.data,
        icon: null,
        logo: null,
      });
    }

    showSuccess('Branding updated successfully');
  } catch (error) {
    console.error('Error saving branding:', error);
    if (isAxiosError(error)) {
      showError(error.response?.data?.message || 'Failed to save branding');
    } else {
      showError('Failed to save branding');
    }
  } finally {
    isSaving.value = false;
  }
};

onMounted(async () => {
  try {
    const response = await $axios.get(`/api/v1/teams/${props.teamKey}/branding`);
    if (response.data) {
      Object.assign(brandingInfo.value, response.data);
      // Initialize local state with server data (no defaults)
      Object.assign(localBrandingInfo.value, {
        ...response.data,
        icon: null,
        logo: null,
      });
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
  gap: 1rem;
  background: white;
  border: 1px solid #d1d5db;
  border-radius: 8px;
  padding: 1rem;
  transition: all 0.2s ease;
}

.color-input-group:focus-within {
  border-color: #3b82f6;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
}

.color-picker-modern {
  width: 60px;
  height: 60px;
  border: 3px solid #e5e7eb;
  border-radius: 12px;
  cursor: pointer;
  background: none;
  padding: 0;
  flex-shrink: 0;
  transition: all 0.2s ease;
}

.color-picker-modern:hover {
  border-color: #9ca3af;
  transform: scale(1.05);
}

.color-picker-modern::-webkit-color-swatch-wrapper {
  padding: 0;
  border-radius: 8px;
  overflow: hidden;
}

.color-picker-modern::-webkit-color-swatch {
  border: none;
  border-radius: 8px;
}

.color-info {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.color-hex {
  font-family: 'SF Mono', 'Monaco', 'Inconsolata', 'Fira Code', monospace;
  font-size: 1rem;
  font-weight: 600;
  color: #374151;
  letter-spacing: 0.05em;
}

.color-hint {
  color: #6b7280;
  font-size: 0.75rem;
  line-height: 1.4;
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
    align-items: center;
    gap: 0.75rem;
    padding: 0.75rem;
  }

  .color-picker-modern {
    width: 50px;
    height: 50px;
  }

  .preference-row {
    flex-direction: column;
    gap: 1rem;
    align-items: stretch;
  }

  .preference-control {
    justify-content: flex-start;
  }

  .save-actions {
    flex-direction: column;
    align-items: stretch;
    gap: 0.75rem;
  }

  .btn-save {
    width: 100%;
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

/* Save Actions */
.save-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  padding: 2rem 0 0.5rem;
  margin-top: 2rem;
  border-top: 1px solid #e5e7eb;
  gap: 1rem;
}

.btn-save {
  min-width: 140px;
  font-weight: 600;
  padding: 0.75rem 1.5rem;
  border-radius: 8px;
  transition: all 0.2s ease;
}

.btn-save:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(59, 130, 246, 0.3);
}

.btn-save:disabled {
  opacity: 0.7;
  cursor: not-allowed;
}

/* Floating Alert Styling */
:deep(.floating-alert) {
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15) !important;
}
</style>