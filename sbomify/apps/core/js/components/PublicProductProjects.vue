<template>
  <PublicCard
    title="Product Projects"
    :brandColor="brandColor"
    :accentColor="accentColor"
    size="lg"
    shadow="md"
  >
    <template #info-notice>
      <span>Projects that are part of this product.</span>
    </template>

    <div v-if="projects.length > 0" class="projects-list">
      <div class="row">
        <div
          v-for="project in projects"
          :key="project.id"
          class="col-12 col-md-6 col-lg-4"
        >
          <div class="project-item">
            <div class="project-icon">
              <i class="fas fa-project-diagram project-type-icon"></i>
            </div>
            <div class="project-info">
              <h6 class="project-name">
                <a v-if="project.is_public"
                   :href="project.public_url"
                   class="project-link">
                  {{ project.name }}
                </a>
                <span v-else class="project-private">
                  {{ project.name }}
                </span>
              </h6>
              <small class="project-type text-muted">
                Project
              </small>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div v-else class="empty-state">
      <div class="empty-icon">
        <i class="fas fa-project-diagram"></i>
      </div>
      <h6 class="empty-title">No projects yet</h6>
      <p class="empty-description text-muted">
        No projects have been added to this product yet.
      </p>
    </div>
  </PublicCard>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import PublicCard from './PublicCard.vue'

interface Project {
  id: string
  name: string
  is_public: boolean
  public_url?: string
}

interface Props {
  productId?: string
  brandColor?: string
  accentColor?: string
}

const props = withDefaults(defineProps<Props>(), {
  productId: '',
  brandColor: '#dcdcdc',
  accentColor: '#7c8b9d'
})

const projects = ref<Project[]>([])

onMounted(async () => {
  if (props.productId) {
    try {
      // Make API call to get product data including projects
      const response = await fetch(`/api/v1/products/${props.productId}`)
      if (!response.ok) {
        throw new Error('Failed to fetch product data')
      }

      const productData = await response.json()
      projects.value = (productData.projects || []).map((project: { id: string; name: string; is_public: boolean }) => ({
        id: project.id,
        name: project.name,
        is_public: project.is_public,
        public_url: project.is_public ? `/public/project/${project.id}/` : ''
      }))
    } catch (error) {
      console.error('Failed to load projects data:', error)
    }
  }
})
</script>

<style scoped>
.projects-list {
  margin-top: 1rem;
}

.project-item {
  display: flex;
  align-items: center;
  padding: 1rem;
  border: 1px solid var(--border-color, #e2e8f0);
  border-radius: 8px;
  margin-bottom: 0.75rem;
  transition: all 0.2s ease;
  background-color: var(--bg-primary, #ffffff);
}

.project-item:hover {
  transform: translateY(-1px);
  box-shadow: 0 2px 8px var(--shadow-color, rgba(0, 0, 0, 0.1));
  border-color: var(--accent-color, #7c8b9d);
}

.project-icon {
  margin-right: 1rem;
  flex-shrink: 0;
}

.project-type-icon {
  font-size: 1.5rem;
  color: var(--accent-color, #7c8b9d);
  width: 2rem;
  text-align: center;
}

.project-info {
  flex: 1;
  min-width: 0;
}

.project-name {
  margin: 0 0 0.25rem 0;
  font-size: 1rem;
  font-weight: 600;
  line-height: 1.2;
}

.project-link {
  color: var(--accent-color, #7c8b9d);
  text-decoration: none;
  transition: color 0.2s ease;
}

.project-link:hover {
  color: var(--brand-color, #dcdcdc);
  text-decoration: underline;
}

.project-private {
  color: var(--text-secondary, #64748b);
}

.project-type {
  font-size: 0.875rem;
  text-transform: uppercase;
  letter-spacing: 0.025em;
  font-weight: 500;
  margin-bottom: 0.25rem;
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
  .project-item {
    padding: 0.75rem;
  }

  .project-icon {
    margin-right: 0.75rem;
  }

  .project-type-icon {
    font-size: 1.25rem;
  }

  .project-name {
    font-size: 0.9rem;
  }

  .project-type {
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