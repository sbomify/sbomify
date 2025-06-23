<template>
  <StandardCard
    title="Component Metadata"
    :collapsible="true"
    :default-expanded="true"
    info-icon="fas fa-info-circle"
    storage-key="component-metadata"
  >
    <template #info-notice>
      <strong>Augmentation:</strong> Enable the <a href="https://sbomify.com/features/generate-collaborate-analyze/" target="_blank" rel="noopener noreferrer" class="text-decoration-none" style="color: #4f46e5;">Augmentation feature</a> to include this metadata in your SBOM
    </template>

    <div class="row gy-4">
      <div class="col-12 col-lg-6">
        <div class="section-content">
          <div class="section-label">Supplier</div>
          <span v-if="isEmpty(metadata.supplier)" class="not-set">Not set yet</span>
          <template v-else>
            <table v-if="hasSupplierInfo">
              <tbody>
                <tr v-if="metadata.supplier.name">
                  <td>Name</td>
                  <td>{{ metadata.supplier.name }}</td>
                </tr>
                <tr v-if="metadata.supplier.url && ((Array.isArray(metadata.supplier.url) && metadata.supplier.url.length > 0 && metadata.supplier.url.some(url => url)) || (typeof metadata.supplier.url === 'string'))">
                  <td>URL{{ Array.isArray(metadata.supplier.url) && metadata.supplier.url.length > 1 ? 's' : '' }}</td>
                  <td>
                    <div v-if="Array.isArray(metadata.supplier.url)">
                      <div v-for="(url, index) in metadata.supplier.url" :key="index" class="mb-1">
                        <a :href="url" target="_blank" rel="noopener noreferrer" class="text-decoration-none">
                          {{ url }}
                          <i class="fas fa-external-link-alt ms-1 text-muted" style="font-size: 0.75rem;"></i>
                        </a>
                      </div>
                    </div>
                    <div v-else>
                      <a :href="metadata.supplier.url" target="_blank" rel="noopener noreferrer" class="text-decoration-none">
                        {{ metadata.supplier.url }}
                        <i class="fas fa-external-link-alt ms-1 text-muted" style="font-size: 0.75rem;"></i>
                      </a>
                    </div>
                  </td>
                </tr>
                <tr v-if="metadata.supplier.address">
                  <td>Address</td>
                  <td>{{ metadata.supplier.address }}</td>
                </tr>
              </tbody>
            </table>
            <span v-else class="not-set">No supplier information provided</span>

            <template v-if="!isEmpty(metadata.supplier.contacts)">
              <div class="sub-section-label mt-4">Contacts</div>
              <div class="contacts">
                <span v-for="(contact, index) in metadata.supplier.contacts" class="contact-item">
                  {{ contact.name }} ({{ contact.email }})
                  <i v-if="showEditButton" class="fa-regular fa-circle-xmark" @click="removeSupplierContact(index)"></i>
                </span>
              </div>
            </template>
          </template>
        </div>
      </div>
      <div class="col-12 col-lg-6">
        <div class="section-content">
          <div class="section-label">Lifecycle</div>
          <span
            v-if="metadata.lifecycle_phase"
            class="badge"
            :class="getLifecyclePhaseClass(metadata.lifecycle_phase)"
          >
            {{ formatLifecyclePhase(metadata.lifecycle_phase) }}
          </span>
          <span v-else class="not-set">Not set yet</span>
        </div>
      </div>
      <div class="col-12 col-lg-6">
        <div class="section-content">
          <div class="section-label">Licenses</div>
          <span v-if="isEmpty(metadata.licenses)" class="not-set">Not set yet</span>
          <span v-else>
            <div class="contacts">
              <span v-for="license in metadata.licenses" class="contact-item">
                <span v-if="typeof license === 'string'">{{ license }}</span>
                <span v-else-if="license && license.name">{{ license.name }} (custom)</span>
              </span>
            </div>
          </span>
        </div>
      </div>
      <div class="col-12 col-lg-6">
        <div class="section-content">
          <div class="section-label">Authors</div>
          <span v-if="isEmpty(metadata.authors)" class="not-set">Not set yet</span>
          <template v-else>
            <div class="contacts">
              <span v-for="(author, index) in metadata.authors" class="contact-item">
                {{ author.name }} ({{ author.email }})
                <i v-if="showEditButton" class="fa-regular fa-circle-xmark" @click="removeAuthor(index)"></i>
              </span>
            </div>
          </template>
        </div>
      </div>
    </div>

    <template v-if="showEditButton" #actions>
      <div class="d-flex gap-2 justify-content-end">
        <button class="btn btn-outline-secondary btn-sm" @click="$emit('copy')">
          <i class="fa-solid fa-copy me-2"></i>
          Copy Metadata
        </button>
        <button class="btn btn-outline-primary btn-sm" @click="$emit('edit')">
          <i class="fa-solid fa-edit me-2"></i>
          Edit Metadata
        </button>
      </div>
    </template>
  </StandardCard>
</template>

<script setup lang="ts">
  import $axios from '../../../core/js/utils';
  import { isEmpty } from '../../../core/js/utils';
  import { isAxiosError } from 'axios';
  import { ref, computed, onMounted } from 'vue';
  import type { SupplierInfo, ComponentMetaInfo, AlertMessage, CustomLicense } from '../type_defs.d.ts';
  import StandardCard from '../../../core/js/components/StandardCard.vue';

  interface Props {
    componentId: string;
    showEditButton?: boolean;
  }

  const props = defineProps<Props>();
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
    licenses: [] as (string | CustomLicense)[],
    lifecycle_phase: null
  });

  const alertMessage = ref<AlertMessage>({
    alertType: null,
    title: null,
    message: null,
  });

  const apiUrl = '/api/v1/sboms/component/' + props.componentId + '/meta';

  const formatLifecyclePhase = (phase: string): string => {
    // Special case for pre/post-build to keep the hyphen
    if (phase === 'pre-build') return 'Pre-Build';
    if (phase === 'post-build') return 'Post-Build';

    // Regular title case for other phases
    return phase.charAt(0).toUpperCase() + phase.slice(1);
  };

  const getComponentMetadata = async () => {
    alertMessage.value = {
      alertType: null,
      title: null,
      message: null,
    };

    try {
      const response = await $axios.get(apiUrl);
      if (response.status < 200 || response.status >= 300) {
        throw new Error('Network response was not ok. ' + response.statusText);
      }
      metadata.value = {...metadata.value, ...response.data};
    } catch (error) {
      console.error(error);
      if (isAxiosError(error)) {
        alertMessage.value = {
          alertType: 'danger',
          title: `${error.response?.status} - ${error.response?.statusText}`,
          message: error.response?.data?.detail[0].msg
        }
      } else {
        alertMessage.value = {
          alertType: 'danger',
          title: 'Error',
          message: 'Failed to load metadata'
        }
      }
    }
  };

  onMounted(() => {
    getComponentMetadata();
  });

  const removeSupplierContact = async (index: number) => {
    if (!metadata.value.supplier?.contacts) return;
    metadata.value.supplier.contacts.splice(index, 1);
    // TODO: Save changes
  };

  const removeAuthor = async (index: number) => {
    if (!metadata.value.authors) return;
    metadata.value.authors.splice(index, 1);
    // TODO: Save changes
  };

  const getLifecyclePhaseClass = (phase: string): string => {
    switch (phase) {
      case 'design':
      case 'pre-build':
        return 'badge-warning';
      case 'build':
      case 'post-build':
      case 'operations':
        return 'badge-success';
      case 'decommission':
        return 'badge-danger';
      default:
        return 'badge-warning';
    }
  };

  const hasSupplierInfo = computed(() => {
    return metadata.value.supplier?.name || metadata.value.supplier?.url || metadata.value.supplier?.address;
  });

</script>

<style scoped>
.section-label {
  font-size: 0.875rem;
  font-weight: 500;
  color: #6c757d;
  margin-bottom: 1rem;
  padding-bottom: 0.5rem;
  border-bottom: 1px solid #dee2e6;
}

.sub-section-label {
  font-size: 0.875rem;
  font-weight: 500;
  color: #6c757d;
  margin-bottom: 0.5rem;
}

.section-content {
  padding: 0;
}

.hint-text {
  padding: 1rem;
  background-color: #f8f9fa;
  border-radius: 0.5rem;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.hint-link {
  color: #0d6efd;
  text-decoration: none;
}

.hint-link:hover {
  text-decoration: underline;
}

.not-set {
  color: #6c757d;
  font-style: italic;
}

table {
  width: 100%;
  margin-bottom: 1rem;
}

td {
  padding: 0.5rem 0;
}

td:first-child {
  width: 100px;
  color: #6c757d;
}

.contacts {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}

.contact-item {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.25rem 0.75rem;
  background-color: #f8f9fa;
  border-radius: 1rem;
  font-size: 0.875rem;
}

.contact-item i {
  cursor: pointer;
  color: #6c757d;
}

.contact-item i:hover {
  color: #dc3545;
}

.badge {
  padding: 0.5rem 1rem;
  border-radius: 0.25rem;
  font-weight: 500;
}

.badge-warning {
  background-color: #fff3cd;
  color: #856404;
}

.badge-success {
  background-color: #d4edda;
  color: #155724;
}

.badge-danger {
  background-color: #f8d7da;
  color: #721c24;
}


</style>