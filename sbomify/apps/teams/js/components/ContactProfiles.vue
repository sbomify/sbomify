<template>
  <StandardCard
    title="Contact Profiles"
    variant="settings"
    size="large"
    shadow="md"
  >
    <template #header-actions>
      <button
        v-if="canManageProfiles"
        class="btn btn-primary btn-sm"
        @click="startCreate"
      >
        <i class="fa-solid fa-plus me-1"></i>
        Add Profile
      </button>
    </template>

    <div v-if="isLoading" class="text-center text-muted py-4">
      <i class="fas fa-spinner fa-spin me-2"></i>Loading contact profiles...
    </div>

    <div v-else>
      <div v-if="!profiles.length" class="empty-state">
        <i class="fas fa-address-book fa-3x text-muted mb-3"></i>
        <h5 class="text-muted mb-2">No contact profiles yet</h5>
        <p class="text-muted">Create a profile to reuse supplier information across components.</p>
      </div>

      <div v-else class="table-responsive">
        <table class="table align-middle">
          <thead>
            <tr>
              <th scope="col">Name</th>
              <th scope="col">Supplier</th>
              <th scope="col">Company</th>
              <th scope="col">Default</th>
              <th scope="col" class="text-end">Actions</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="profile in profiles" :key="profile.id">
              <td>
                <div class="fw-semibold">{{ profile.name }}</div>
                <div v-if="profile.email" class="text-muted small">
                  <i class="fas fa-envelope me-1"></i>{{ profile.email }}
                </div>
              </td>
              <td>
                <span v-if="profile.supplier_name" class="badge bg-primary-subtle text-primary">
                  {{ profile.supplier_name }}
                </span>
                <span v-else class="text-muted">Not set</span>
              </td>
              <td>
                <span v-if="profile.company">{{ profile.company }}</span>
                <span v-else class="text-muted">—</span>
              </td>
              <td>
                <span v-if="profile.is_default" class="badge bg-success-subtle text-success">
                  Default
                </span>
              </td>
              <td class="text-end">
                <div class="btn-group btn-group-sm" role="group">
                  <button
                    class="btn btn-outline-secondary"
                    :disabled="!canManageProfiles"
                    @click="startEdit(profile)"
                  >
                    <i class="fas fa-edit"></i>
                  </button>
                  <button
                    class="btn btn-outline-primary"
                    :disabled="!canManageProfiles || profile.is_default"
                    @click="setDefault(profile)"
                  >
                    <i class="fas fa-star"></i>
                  </button>
                  <button
                    class="btn btn-outline-danger"
                    :disabled="!canManageProfiles"
                    @click="deleteProfile(profile)"
                  >
                    <i class="fas fa-trash"></i>
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div v-if="showForm" class="profile-form mt-4">
      <h5 class="mb-3">{{ editingProfileId ? 'Edit' : 'Create' }} Contact Profile</h5>
      <div class="row g-4">
        <div class="col-12 col-lg-6">
          <div class="mb-3">
            <label class="form-label">Profile Name <span class="text-danger">*</span></label>
            <input v-model="formState.name" type="text" class="form-control" required>
          </div>
          <div class="mb-3">
            <label class="form-label">Company</label>
            <input v-model="formState.company" type="text" class="form-control" placeholder="Company name">
          </div>
          <div class="mb-3">
            <label class="form-label">Supplier Name</label>
            <input v-model="formState.supplierName" type="text" class="form-control" placeholder="Supplier name">
          </div>
          <div class="mb-3">
            <label class="form-label">Vendor</label>
            <input v-model="formState.vendor" type="text" class="form-control" placeholder="Vendor name">
          </div>
          <div class="mb-3">
            <label class="form-label">Email</label>
            <input v-model="formState.email" type="email" class="form-control" placeholder="contact@example.com">
          </div>
          <div class="mb-3">
            <label class="form-label">Phone</label>
            <input v-model="formState.phone" type="tel" class="form-control" placeholder="+1 555 123 4567">
          </div>
        </div>
        <div class="col-12 col-lg-6">
          <div class="mb-3">
            <label class="form-label">Website</label>
            <div v-for="(_, index) in formState.websiteUrls" :key="`url-${index}`" class="input-group mb-2">
              <input v-model="formState.websiteUrls[index]" type="url" class="form-control" placeholder="https://example.com">
              <button type="button" class="btn btn-outline-danger" @click="removeWebsiteUrl(index)">
                <i class="fa-solid fa-times"></i>
              </button>
            </div>
            <div class="input-group">
              <input
                v-model="newWebsiteUrl"
                type="url"
                class="form-control"
                placeholder="https://example.com"
                @keyup.enter="addWebsiteUrl"
              >
              <button type="button" class="btn btn-outline-primary" @click="addWebsiteUrl">
                <i class="fa-solid fa-plus"></i>
              </button>
            </div>
          </div>
          <div class="mb-3">
            <label class="form-label">Address</label>
            <textarea v-model="formState.address" class="form-control" rows="3" placeholder="Street, City, Country"></textarea>
          </div>
          <div class="mb-3">
            <label class="form-label">Contacts</label>
            <ContactsEditor v-model="formState.contacts" contact-type="contact" />
          </div>
          <div class="form-check mb-3">
            <input
              id="profile-default"
              v-model="formState.isDefault"
              class="form-check-input"
              type="checkbox"
            >
            <label class="form-check-label" for="profile-default">
              Set as default profile
            </label>
          </div>
        </div>
      </div>
      <div class="d-flex justify-content-end gap-2">
        <button
          class="btn btn-outline-secondary"
          type="button"
          @click="cancelForm"
        >
          Cancel
        </button>
        <button
          class="btn btn-success"
          type="button"
          :disabled="isSaving || !formState.name"
          @click="submitForm"
        >
          <span v-if="isSaving">
            <i class="fas fa-spinner fa-spin me-2"></i>Saving...
          </span>
          <span v-else>
            <i class="fas fa-save me-2"></i>Save Profile
          </span>
        </button>
      </div>
    </div>
  </StandardCard>
</template>

<script setup lang="ts">
import { computed, ref, onMounted } from 'vue';
import ContactsEditor from '@/sbomify/apps/sboms/js/components/ContactsEditor.vue';
import StandardCard from '../../../core/js/components/StandardCard.vue';
import { showError, showSuccess } from '../../../core/js/alerts';
import $axios from '../../../core/js/utils';
import type { ContactInfo, ContactProfile } from '../../../core/js/type_defs';

interface Props {
  teamKey: string;
  userRole: string;
}

const props = defineProps<Props>();

interface ContactProfileForm {
  name: string;
  company: string;
  supplierName: string;
  vendor: string;
  email: string;
  phone: string;
  address: string;
  websiteUrls: string[];
  contacts: ContactInfo[];
  isDefault: boolean;
}

const profiles = ref<ContactProfile[]>([]);
const isLoading = ref(true);
const isSaving = ref(false);
const showForm = ref(false);
const editingProfileId = ref<string | null>(null);
const newWebsiteUrl = ref('');

const defaultForm: ContactProfileForm = {
  name: '',
  company: '',
  supplierName: '',
  vendor: '',
  email: '',
  phone: '',
  address: '',
  websiteUrls: [],
  contacts: [],
  isDefault: false,
};

const formState = ref<ContactProfileForm>({ ...defaultForm });

const canManageProfiles = computed(() => ['owner', 'admin'].includes(props.userRole));

const resetForm = () => {
  formState.value = { ...defaultForm };
  newWebsiteUrl.value = '';
  editingProfileId.value = null;
};

const transformProfile = (profile: ContactProfileForm) => {
  const payload = {
    name: profile.name.trim(),
    company: profile.company.trim() || null,
    supplier_name: profile.supplierName.trim() || null,
    vendor: profile.vendor.trim() || null,
    email: profile.email.trim() || null,
    phone: profile.phone.trim() || null,
    address: profile.address.trim() || null,
    website_urls: profile.websiteUrls.filter((url) => url && url.trim())
      .map((url) => url.trim()),
    contacts: profile.contacts
      .filter((contact) => contact.name)
      .map((contact, index) => ({
        name: contact.name?.trim() ?? '',
        email: contact.email?.trim() || null,
        phone: contact.phone?.trim() || null,
        order: index,
      })),
    is_default: profile.isDefault,
  };

  return payload;
};

const loadProfiles = async () => {
  isLoading.value = true;
  try {
    const response = await $axios.get(`/api/v1/workspaces/${props.teamKey}/contact-profiles`);
    const data = (response.data ?? []) as ContactProfile[];
    profiles.value = data.map((profile) => ({
      ...profile,
      website_urls: profile.website_urls ?? [],
      contacts: profile.contacts ?? [],
    }));
  } catch (error) {
    console.error('Failed to load contact profiles', error);
    showError('Failed to load contact profiles');
  } finally {
    isLoading.value = false;
  }
};

const startCreate = () => {
  if (!canManageProfiles.value) return;
  resetForm();
  showForm.value = true;
};

const startEdit = (profile: ContactProfile) => {
  if (!canManageProfiles.value) return;
  editingProfileId.value = profile.id;
  formState.value = {
    name: profile.name || '',
    company: profile.company || '',
    supplierName: profile.supplier_name || '',
    vendor: profile.vendor || '',
    email: profile.email || '',
    phone: profile.phone || '',
    address: profile.address || '',
    websiteUrls: [...(profile.website_urls || [])],
    contacts: (profile.contacts || []).map((contact) => ({
      name: contact.name,
      email: contact.email ?? null,
      phone: contact.phone ?? null,
    })),
    isDefault: profile.is_default ?? false,
  };
  showForm.value = true;
};

const cancelForm = () => {
  resetForm();
  showForm.value = false;
};

const addWebsiteUrl = () => {
  if (newWebsiteUrl.value && newWebsiteUrl.value.trim()) {
    formState.value.websiteUrls.push(newWebsiteUrl.value.trim());
    newWebsiteUrl.value = '';
  }
};

const removeWebsiteUrl = (index: number) => {
  formState.value.websiteUrls.splice(index, 1);
};

const submitForm = async () => {
  if (!canManageProfiles.value || !formState.value.name.trim()) {
    return;
  }

  isSaving.value = true;
  try {
    const payload = transformProfile(formState.value);
    if (editingProfileId.value) {
      await $axios.patch(
        `/api/v1/workspaces/${props.teamKey}/contact-profiles/${editingProfileId.value}`,
        payload,
      );
      showSuccess('Contact profile updated');
    } else {
      await $axios.post(`/api/v1/workspaces/${props.teamKey}/contact-profiles`, payload);
      showSuccess('Contact profile created');
    }

    await loadProfiles();
    cancelForm();
  } catch (error) {
    console.error('Failed to save contact profile', error);
    showError('Failed to save contact profile');
  } finally {
    isSaving.value = false;
  }
};

const setDefault = async (profile: ContactProfile) => {
  if (!canManageProfiles.value || profile.is_default) {
    return;
  }

  try {
    await $axios.patch(`/api/v1/workspaces/${props.teamKey}/contact-profiles/${profile.id}`, {
      is_default: true,
    });
    showSuccess(`'${profile.name}' set as default profile`);
    await loadProfiles();
  } catch (error) {
    console.error('Failed to set default profile', error);
    showError('Failed to set default profile');
  }
};

const deleteProfile = async (profile: ContactProfile) => {
  if (!canManageProfiles.value) {
    return;
  }

  if (!confirm(`Delete contact profile "${profile.name}"?`)) {
    return;
  }

  try {
    await $axios.delete(`/api/v1/workspaces/${props.teamKey}/contact-profiles/${profile.id}`);
    showSuccess('Contact profile deleted');
    await loadProfiles();
  } catch (error) {
    console.error('Failed to delete contact profile', error);
    showError('Failed to delete contact profile');
  }
};

onMounted(loadProfiles);
</script>

<style scoped>
.empty-state {
  text-align: center;
  padding: 3rem 1rem;
  border: 1px dashed #dee2e6;
  border-radius: 0.75rem;
  background: #f8fafc;
}

.profile-form {
  border-top: 1px solid #e5e9f2;
  padding-top: 1.5rem;
}

.profile-form textarea {
  resize: vertical;
}

.btn-group .btn {
  min-width: 2.5rem;
}

.input-group .btn {
  border-top-left-radius: 0;
  border-bottom-left-radius: 0;
}

.input-group .form-control {
  border-top-right-radius: 0;
  border-bottom-right-radius: 0;
}
</style>
