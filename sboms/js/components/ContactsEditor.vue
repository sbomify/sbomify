<template>
  <div v-if="modelValue && modelValue.length" class="contacts">
    <div v-for="(contact, contactIndex) in modelValue" class="contact-badge">
      {{ contact.name }} ({{ contact.email }})
      <i v-if="addingContact" class="far fa-times-circle" @click="removeContact(contactIndex)"></i>
    </div>
  </div>

  <div v-if="addingContact" class="contact-form">
    <div class="form-group">
      <label class="form-label">Name <span class="text-danger">*</span></label>
      <input
        v-model="newContactData.name"
        type="text"
        class="form-control"
        :class="{ 'is-invalid': formErrors.name }"
        placeholder="Enter name"
        @keyup.enter="saveContact"
      >
      <div v-if="formErrors.name" class="invalid-feedback">
        {{ formErrors.name }}
      </div>
    </div>

    <div class="form-group">
      <label class="form-label">Email</label>
      <input
        v-model="newContactData.email"
        type="email"
        class="form-control"
        :class="{ 'is-invalid': formErrors.email }"
        placeholder="Enter email address"
        @keyup.enter="saveContact"
      >
      <div v-if="formErrors.email" class="invalid-feedback">
        {{ formErrors.email }}
      </div>
    </div>

    <div class="form-group">
      <label class="form-label">Phone</label>
      <input
        v-model="newContactData.phone"
        type="tel"
        class="form-control"
        :class="{ 'is-invalid': formErrors.phone }"
        placeholder="Enter phone number"
        @keyup.enter="saveContact"
      >
      <div v-if="formErrors.phone" class="invalid-feedback">
        {{ formErrors.phone }}
      </div>
    </div>

    <div class="actions">
      <button
        class="btn btn-outline"
        @click="cancelAddContact"
      >
        <i class="far fa-times"></i>
        Cancel
      </button>
      <button
        class="btn btn-primary"
        :disabled="!newContactData.name"
        @click="saveContact"
      >
        <i class="far fa-check"></i>
        Save {{ props.contactType }}
      </button>
    </div>
  </div>

  <button v-else class="add-contact-button" @click="startAddContact">
    <i class="fa-solid fa-circle-plus"></i>
    Add {{ props.contactType }}{{ modelValue.length ? ' another' : '' }}
  </button>
</template>

<script setup lang="ts">
import { ref } from 'vue';
import type { ContactInfo } from '../type_defs';

interface Props {
  modelValue: ContactInfo[];
  contactType: string;
  validationErrors?: Record<string, string>;
}

const props = defineProps<Props>();
const emits = defineEmits(['update:modelValue']);

const addingContact = ref(false);
const newContactData = ref<ContactInfo>({
  name: "",
  email: "",
  phone: ""
});

const formErrors = ref<Record<string, string>>({});

const isValidEmail = (email: string): boolean => {
  if (!email) return true; // Empty email is valid (it's optional)
  const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  return emailRegex.test(email);
};

const validateForm = (): boolean => {
  formErrors.value = {};

  // Name is required
  if (!newContactData.value.name?.trim()) {
    formErrors.value.name = 'Name is required';
  }

  // Email is optional but must be valid if provided
  if (newContactData.value.email && !isValidEmail(newContactData.value.email)) {
    formErrors.value.email = 'Please enter a valid email address';
  }

  return Object.keys(formErrors.value).length === 0;
};

const startAddContact = () => {
  formErrors.value = {};
  addingContact.value = true;
  // Focus the name input after the form appears
  setTimeout(() => {
    const nameInput = document.querySelector('input[type="text"]') as HTMLInputElement;
    if (nameInput) nameInput.focus();
  }, 0);
};

const saveContact = () => {
  if (!validateForm()) return;

  emits('update:modelValue', [...props.modelValue, { ...newContactData.value }]);

  // Clear form
  newContactData.value = {
    name: "",
    email: "",
    phone: ""
  };
  formErrors.value = {};

  // Keep form open for adding multiple contacts
  if (!props.modelValue.length) {
    addingContact.value = false;
  }
};

const cancelAddContact = () => {
  addingContact.value = false;
  newContactData.value = {
    name: "",
    email: "",
    phone: ""
  };
  formErrors.value = {};
};

const removeContact = (contactIndex: number) => {
  const newContacts = [...props.modelValue];
  newContacts.splice(contactIndex, 1);
  emits('update:modelValue', newContacts);
};

// TODO: The 'license' field is temporary and will be removed in the future.
// It will be generated ad-hoc from the view for backward compatibility.
</script>

<style scoped>
.contacts {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  margin-bottom: 1.5rem;
}

.contact-badge {
  background-color: #f8f9fa;
  border: 1px solid #eaecef;
  border-radius: 20px;
  padding: 0.5rem 1rem;
  display: inline-flex;
  align-items: center;
  gap: 0.75rem;
  color: #6c757d;
  font-size: 0.875rem;
}

.contact-badge i {
  cursor: pointer;
  color: #6c757d;
  transition: all 0.2s ease;
  font-size: 0.875rem;
}

.contact-badge i:hover {
  color: #dc3545;
}

.contact-info {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.contact-name {
  font-weight: 500;
  color: #2c3e50;
}

.contact-details {
  color: #6c757d;
  font-size: 0.875rem;
}

/* For supplier contacts */
.contact-badge[data-type="contact"] {
  padding: 0.5rem 0.75rem;
  font-size: 0.875rem;
}

.contact-badge[data-type="contact"] .contact-details {
  color: #2c3e50;
  font-size: inherit;
}

/* For author contacts */
.contact-badge[data-type="author"] {
  padding: 0.75rem 1rem;
}

.contact-form {
  background: #ffffff;
  border: 1px solid #dee2e6;
  border-radius: 6px;
  padding: 1.5rem;
  margin-bottom: 1rem;
}

.form-group {
  margin-bottom: 1rem;
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

.form-control.is-invalid {
  border-color: #dc3545;
}

.invalid-feedback {
  display: block;
  color: #dc3545;
  font-size: 0.875rem;
  margin-top: 0.25rem;
}

.actions {
  display: flex;
  gap: 1rem;
  margin-top: 1rem;
}

.btn {
  flex: 1;
  padding: 0.75rem;
  border-radius: 6px;
  font-weight: 500;
  transition: all 0.2s ease;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
}

.btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.btn-primary {
  background: #0d6efd;
  border: none;
  color: #ffffff;
}

.btn-primary:hover:not(:disabled) {
  background: #0b5ed7;
  transform: translateY(-1px);
}

.btn-outline {
  background: transparent;
  border: 1px solid #dee2e6;
  color: #6c757d;
}

.btn-outline:hover {
  background: #f8f9fa;
  border-color: #6c757d;
  color: #495057;
}

.add-contact-button {
  width: 100%;
  padding: 0.75rem;
  background: #f8f9fa;
  border: 1px dashed #dee2e6;
  border-radius: 6px;
  color: #6c757d;
  transition: all 0.2s ease;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
}

.add-contact-button:hover {
  background: #ffffff;
  border-color: #0d6efd;
  color: #0d6efd;
}

.add-contact-button i {
  font-size: 0.875rem;
}
</style>

