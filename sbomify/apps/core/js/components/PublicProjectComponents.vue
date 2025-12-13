<template>
  <PublicCard
    title="Project Components"
    :brandColor="brandColor"
    :accentColor="accentColor"
    size="lg"
    shadow="md"
  >
    <template #info-notice>
      <span>Components that are part of this project.</span>
    </template>

    <div v-if="components.length > 0" class="components-list">
      <div class="row">
        <div
          v-for="component in components"
          :key="component.id"
          class="col-12 col-md-6 col-lg-4"
        >
          <div class="component-item">
            <div class="component-icon">
              <i :class="getComponentIcon(component.component_type)" class="component-type-icon"></i>
            </div>
            <div class="component-info">
              <h6 class="component-name">
                <a v-if="component.is_public"
                   :href="component.public_url"
                   class="component-link">
                  {{ component.name }}
                </a>
                <span v-else class="component-private">
                  {{ component.name }}
                </span>
              </h6>
              <small class="component-type text-muted">
                {{ getComponentTypeDisplay(component.component_type) }}
              </small>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div v-else class="empty-state">
      <div class="empty-icon">
        <i class="fas fa-cube"></i>
      </div>
      <h6 class="empty-title">No components yet</h6>
      <p class="empty-description text-muted">
        No components have been added to this project yet.
      </p>
    </div>
  </PublicCard>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import PublicCard from './PublicCard.vue'

interface Component {
  id: string
  name: string
  slug?: string
  component_type: string
  is_public: boolean
  public_url?: string
}

interface Props {
  projectId?: string
  brandColor?: string
  accentColor?: string
  isCustomDomain?: boolean | string
}

const props = withDefaults(defineProps<Props>(), {
  projectId: '',
  brandColor: '#dcdcdc',
  accentColor: '#7c8b9d',
  isCustomDomain: false
})

const isCustomDomain = computed(() => {
  if (typeof props.isCustomDomain === 'string') {
    return props.isCustomDomain === 'true'
  }
  return props.isCustomDomain
})

const getComponentUrl = (component: Component): string => {
  if (isCustomDomain.value) {
    return `/component/${component.slug || component.id}/`
  }
  return `/public/component/${component.id}/`
}

const components = ref<Component[]>([])

onMounted(async () => {
  if (props.projectId) {
    try {
      // Make API call to get project data including components
      const response = await fetch(`/api/v1/projects/${props.projectId}`)
      if (!response.ok) {
        throw new Error('Failed to fetch project data')
      }

      const projectData = await response.json()
      components.value = (projectData.components || []).map((component: { id: string; name: string; slug?: string; component_type: string; is_public: boolean }) => {
        const componentData: Component = {
          id: component.id,
          name: component.name,
          slug: component.slug,
          component_type: component.component_type,
          is_public: component.is_public,
          public_url: ''
        }
        componentData.public_url = component.is_public ? getComponentUrl(componentData) : ''
        return componentData
      })
    } catch (error) {
      console.error('Failed to load components data:', error)
    }
  }
})

const getComponentIcon = (componentType: string): string => {
  switch (componentType) {
    case 'sbom':
      return 'fas fa-file-code'
    case 'document':
      return 'fas fa-file-alt'
    default:
      return 'fas fa-cube'
  }
}

const getComponentTypeDisplay = (componentType: string): string => {
  switch (componentType) {
    case 'sbom':
      return 'SBOM'
    case 'document':
      return 'Document'
    default:
      return 'Component'
  }
}
</script>

<style scoped>
.components-list {
  margin-top: 1rem;
}

.component-item {
  display: flex;
  align-items: center;
  padding: 1rem;
  border: 1px solid var(--border-color, #e2e8f0);
  border-radius: 8px;
  margin-bottom: 0.75rem;
  transition: all 0.2s ease;
  background-color: var(--bg-primary, #ffffff);
}

.component-item:hover {
  transform: translateY(-1px);
  box-shadow: 0 2px 8px var(--shadow-color, rgba(0, 0, 0, 0.1));
  border-color: var(--accent-color, #7c8b9d);
}

.component-icon {
  margin-right: 1rem;
  flex-shrink: 0;
}

.component-type-icon {
  font-size: 1.5rem;
  color: var(--accent-color, #7c8b9d);
  width: 2rem;
  text-align: center;
}

.component-info {
  flex: 1;
  min-width: 0;
}

.component-name {
  margin: 0 0 0.25rem 0;
  font-size: 1rem;
  font-weight: 600;
  line-height: 1.2;
}

.component-link {
  color: var(--accent-color, #7c8b9d);
  text-decoration: none;
  transition: color 0.2s ease;
}

.component-link:hover {
  color: var(--brand-color, #dcdcdc);
  text-decoration: underline;
}

.component-private {
  color: var(--text-secondary, #64748b);
}

.component-type {
  font-size: 0.875rem;
  text-transform: uppercase;
  letter-spacing: 0.025em;
  font-weight: 500;
}

.empty-state {
  text-align: center;
  padding: 2rem 1rem;
}

.empty-icon {
  margin-bottom: 1rem;
}

.empty-icon i {
  font-size: 3rem;
  color: var(--text-muted, #94a3b8);
}

.empty-title {
  font-size: 1.125rem;
  font-weight: 600;
  color: var(--text-secondary, #64748b);
  margin-bottom: 0.5rem;
}

.empty-description {
  font-size: 0.875rem;
  margin-bottom: 0;
  max-width: 300px;
  margin-left: auto;
  margin-right: auto;
}

/* Responsive design */
@media (max-width: 768px) {
  .component-item {
    padding: 0.75rem;
  }

  .component-icon {
    margin-right: 0.75rem;
  }

  .component-type-icon {
    font-size: 1.25rem;
  }

  .component-name {
    font-size: 0.9rem;
  }

  .component-type {
    font-size: 0.8rem;
  }

  .empty-state {
    padding: 1.5rem 1rem;
  }

  .empty-icon i {
    font-size: 2.5rem;
  }
}
</style>