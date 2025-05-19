<template>
  <div class="container-fluid p-0">
    <div class="card">
      <div class="card-body">
        <h4 class="d-flex justify-content-between align-items-center mb-4" style="cursor: pointer;" @click="toggleExpand">
          Component Metadata
          <div class="d-flex align-items-center">
            <button v-if="showEditButton" class="btn btn-link p-0 me-2" style="font-size: inherit;" @click.stop="$emit('edit')">
              <i class="fa-solid fa-pen"></i>
            </button>
            <svg v-if="!isExpanded" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"></polyline></svg>
            <svg v-if="isExpanded" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"></polyline></svg>
          </div>
        </h4>
        <div v-if="isExpanded">
          <div class="hint-text mb-4">
            <i class="fa-regular fa-lightbulb text-muted"></i>
            <span>Enable the <a href="https://sbomify.com/features/generate-collaborate-analyze/" target="_blank" rel="noopener noreferrer" class="hint-link">Augmentation</a> feature to include this metadata in your SBOM</span>
          </div>
          <div class="row gy-4">
            <div class="col-12 col-lg-6">
              <div class="section-content">
                <div class="section-label">Supplier</div>
                <dl>
                  <dt>Name</dt>
                  <dd>
                    <div v-if="metadata.supplier && metadata.supplier.name">{{ metadata.supplier.name }}</div>
                    <div v-else>Not set</div>
                  </dd>
                  <dt>URL</dt>
                  <dd>
                    <div v-if="metadata.supplier && metadata.supplier.url">
                      <a :href="metadata.supplier.url" target="_blank">{{ metadata.supplier.url }}</a>
                    </div>
                    <div v-else>Not set</div>
                  </dd>
                  <dt>Address</dt>
                  <dd>
                    <div v-if="metadata.supplier && metadata.supplier.address">{{ metadata.supplier.address }}</div>
                    <div v-else>Not set</div>
                  </dd>
                </dl>
                <div v-if="metadata.supplier && metadata.supplier.contacts && metadata.supplier.contacts.length">
                  <div class="sub-section-label mt-4">Contacts</div>
                  <ul>
                    <li v-for="(contact, idx) in metadata.supplier.contacts" :key="idx">
                      {{ contact.name }}<span v-if="contact.email"> ({{ contact.email }})</span><span v-if="contact.phone">, {{ contact.phone }}</span>
                    </li>
                  </ul>
                </div>
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
                <div class="section-label">License</div>
                <span v-if="!metadata.license_expression && isEmpty(metadata.license)" class="not-set">Not set yet</span>
                <span v-else>
                  <div class="license-info">
                    <div v-if="metadata.license_expression" class="license-expression">
                      <strong>Expression:</strong> {{ metadata.license_expression }}
                    </div>
                    <div v-if="!isEmpty(metadata.license)" class="license-list">
                      <strong>Legacy:</strong>
                      <div class="contacts">
                        <span v-for="license in metadata.license" class="contact-item">
                          <span v-if="typeof license === 'string'">{{ license }}</span>
                          <span v-else-if="license && license.name">{{ license.name }} (custom)</span>
                        </span>
                      </div>
                    </div>
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
  import { ref, onMounted } from 'vue';
  import type { SupplierInfo, ComponentMetaInfo, AlertMessage, CustomLicense } from '../type_defs.d.ts';

  interface Props {
    componentId: string;
    showEditButton?: boolean;
  }

  const props = defineProps<Props>();
  const isExpanded = ref(true);
  const metadata = ref<ComponentMetaInfo>({
    supplier: {
      name: null,
      url: null,
      address: null,
      contacts: []
    } as SupplierInfo,
    authors: [],
    license_expression: null,
    license: [] as (string | CustomLicense)[],
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

dl {
  margin: 0;
}

dt {
  font-weight: 600;
  margin-top: 1rem;
}

dd {
  margin-left: 0;
  margin-bottom: 0.5rem;
}

ul {
  margin: 0.25rem 0 0.5rem 1.5rem;
  padding: 0;
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