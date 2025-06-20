<template>
  <div class="container-fluid p-0">
    <div class="card">
      <div class="card-body">
        <div class="component-metadata-header d-flex justify-content-between align-items-start mb-4">
          <div class="flex-grow-1" style="cursor: pointer;" @click="toggleExpand">
            <h4 class="mb-2 d-flex align-items-center">
              Component Metadata
              <svg v-if="!isExpanded" xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="ms-2"><polyline points="9 18 15 12 9 6"></polyline></svg>
              <svg v-if="isExpanded" xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="ms-2"><polyline points="6 9 12 15 18 9"></polyline></svg>
            </h4>
                         <div class="augmentation-notice d-flex align-items-center">
               <i class="fa-regular fa-lightbulb me-2" style="color: #4f46e5;"></i>
               <span class="text-muted">
                 Enable the <a href="https://sbomify.com/features/generate-collaborate-analyze/" target="_blank" rel="noopener noreferrer" class="text-decoration-none" style="color: #4f46e5;">Augmentation</a> feature to include this metadata in your SBOM
               </span>
             </div>
          </div>
          <div v-if="showEditButton" class="d-flex gap-2">
            <button class="btn btn-outline-secondary btn-sm" @click.stop="$emit('copy')">
              <i class="fa-solid fa-copy me-2"></i>
              Copy
            </button>
            <button class="btn btn-outline-primary btn-sm" @click.stop="$emit('edit')">
              <i class="fa-solid fa-edit me-2"></i>
              Edit
            </button>
          </div>
        </div>
        <div v-if="isExpanded">
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
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
  import $axios from '../../../core/js/utils';
  import { isEmpty } from '../../../core/js/utils';
  import { isAxiosError } from 'axios';
  import { ref, computed, onMounted } from 'vue';
  import type { SupplierInfo, ComponentMetaInfo, AlertMessage, CustomLicense } from '../type_defs.d.ts';

  interface Props {
    componentId: string;
    showEditButton?: boolean;
  }

  const props = defineProps<Props>();
  const isExpanded = ref(true);
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

  const toggleExpand = () => {
    isExpanded.value = !isExpanded.value;
  };

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

.btn-outline-primary {
  border: 1px solid #4f46e5;
  color: #4f46e5;
  background: transparent;
  border-radius: 0.375rem;
  font-weight: 500;
  transition: all 0.2s ease;
}

.btn-outline-primary:hover {
  background: linear-gradient(135deg, #4f46e5 0%, #4338ca 100%);
  border-color: #4f46e5;
  color: white;
  box-shadow: 0 2px 4px rgba(79, 70, 229, 0.15);
  transform: translateY(-1px);
}

.btn-outline-secondary {
  border: 1px solid #64748b;
  color: #64748b;
  background: transparent;
  border-radius: 0.375rem;
  font-weight: 500;
  transition: all 0.2s ease;
}

.btn-outline-secondary:hover {
  background: linear-gradient(135deg, #64748b 0%, #475569 100%);
  border-color: #64748b;
  color: white;
  box-shadow: 0 2px 4px rgba(100, 116, 139, 0.15);
  transform: translateY(-1px);
}
</style>